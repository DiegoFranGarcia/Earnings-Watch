"""sec_daily_index checks every morning that recent business days have their index in bronze.

On 2026-11-06 the run that should have landed 2026-11-05 failed on all its tries (an expired
AWS login on the laptop that then ran Airflow), before alerts existed; the next runs each fetched
only their own day, so the day stayed missing until a manual reconciliation found it on
2026-11-21. check_landed_days fails, and so alerts, while such a gap is recent. These tests hold
how it is wired; the check itself is tested in tests/unit/test_daily_index.py.

Needs Airflow, like test_dag_integrity.py (scripts/test_dags.sh).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("airflow")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

DAG_FILE = Path(__file__).resolve().parents[2] / "airflow" / "dags" / "sec_daily_index.py"


@pytest.fixture(scope="module")
def dag():
    bag = DagBag(dag_folder=str(DAG_FILE))
    assert not bag.import_errors, bag.import_errors
    return bag.dags["sec_daily_index"]


def test_the_check_runs_after_the_landing_whatever_happened_to_it(dag) -> None:
    check = dag.get_task("check_landed_days")
    assert check.upstream_task_ids == {"to_silver"}
    # all_done: it also runs when today's landing failed or was skipped.
    assert check.trigger_rule == "all_done"


def test_the_check_fails_once_and_alerts(dag) -> None:
    check = dag.get_task("check_landed_days")
    assert check.retries == 0  # a gap does not heal by retrying minutes later
    callbacks = check.on_failure_callback
    callbacks = callbacks if isinstance(callbacks, list) else [callbacks]
    assert "notify_failure" in {getattr(callback, "__name__", "") for callback in callbacks}


def test_a_gap_never_holds_back_todays_data(dag) -> None:
    # Only to_silver announces new silver (snowflake_load_daily_index starts from it); the check
    # announces nothing and nothing runs after it.
    assert not dag.get_task("check_landed_days").outlets
    assert not dag.get_task("check_landed_days").downstream_task_ids
    assert [a.name for a in dag.get_task("to_silver").outlets] == ["silver_daily_index"]
