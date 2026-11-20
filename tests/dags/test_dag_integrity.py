"""DAG integrity: every DAG imports without touching the network, and every task follows the
project's operating rules.

Needs Airflow, its providers and Cosmos, so it runs inside the Airflow image (scripts/test_dags.sh)
and is skipped anywhere they are not installed.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

pytest.importorskip("airflow")
pytest.importorskip("cosmos")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAGS = Path(__file__).resolve().parents[2] / "airflow" / "dags"

EXPECTED_DAGS = {
    "company_tickers_snapshot",
    "dbt_build",
    "publish_site",
    "record_task_history",
    "sec_daily_index",
    "sec_fsds_quarterly",
    "snowflake_load",
    "snowflake_load_daily_index",
}


def _no_network(*args, **kwargs):
    raise RuntimeError("network access while parsing a DAG file")


@pytest.fixture(scope="module")
def dagbag():
    # Airflow re-parses DAG files every few minutes: any connection made at import time would
    # run constantly. With connections blocked, one becomes an import error naming its file.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", _no_network)
        patch.setattr(socket, "create_connection", _no_network)
        patch.setattr(socket, "getaddrinfo", _no_network)
        bag = DagBag(dag_folder=str(DAGS))
    return bag


def _tasks(dagbag):
    return [(dag_id, task) for dag_id, dag in dagbag.dags.items() for task in dag.tasks]


def test_every_dag_imports_without_errors_or_network_access(dagbag) -> None:
    assert not dagbag.import_errors, dagbag.import_errors


def test_exactly_the_expected_dags_exist(dagbag) -> None:
    assert set(dagbag.dag_ids) == EXPECTED_DAGS


def test_every_task_has_retries_and_a_timeout(dagbag) -> None:
    missing = [
        f"{dag_id}.{task.task_id}"
        for dag_id, task in _tasks(dagbag)
        if task.retries is None or task.execution_timeout is None
    ]
    assert not missing, f"tasks without retries or a timeout: {missing}"


def test_every_task_alerts_when_it_fails(dagbag) -> None:
    def callback_names(task) -> set[str]:
        callbacks = task.on_failure_callback or []
        callbacks = callbacks if isinstance(callbacks, list) else [callbacks]
        return {getattr(callback, "__name__", "") for callback in callbacks}

    silent = [
        f"{dag_id}.{task.task_id}"
        for dag_id, task in _tasks(dagbag)
        if "notify_failure" not in callback_names(task)
    ]
    assert not silent, f"tasks that would fail silently: {silent}"


def test_every_task_is_owned_by_the_project(dagbag) -> None:
    owners = {task.owner for _, task in _tasks(dagbag)}
    assert owners == {"earningswatch"}, owners
