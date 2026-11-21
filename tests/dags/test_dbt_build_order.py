"""dbt_build runs each test only once everything it reads is rebuilt, and no failing test lets the
marts Asset update (which is what starts publish_site).

On 2026-11-21 the relationship tests between the company pages' tables and the screener ran in
the screener's own test task (dbt's `test --select export_screener` picks up every test that
reads the screener), before the company tables were rebuilt: today's screener against
yesterday's company tables. Cosmos now runs a test with more than one parent as its own task,
after all of them (should_detach_multiple_parents_tests). These tests hold that order, and that
such a task still stands between the build and `publish`.

Needs Airflow, Cosmos and dbt's manifest, like test_dag_integrity.py (scripts/test_dags.sh).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("airflow")
pytest.importorskip("cosmos")

from airflow.dag_processing.dagbag import DagBag  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DAG_FILE = ROOT / "airflow" / "dags" / "warehouse_build.py"
MANIFEST = Path(os.environ.get("DBT_PROJECT_DIR", ROOT / "dbt")) / "target" / "manifest.json"

EXPORTS = ("export_screener", "export_company_quarters", "export_company_history")
# The company pages' tables hold only screener companies: each table's test, by the table.
RELATIONSHIPS = {
    table: f"relationships_{table}_cik__cik__ref_export_screener_"
    for table in ("export_company_quarters", "export_company_history")
}


@pytest.fixture(scope="module")
def dag():
    bag = DagBag(dag_folder=str(DAG_FILE))
    assert not bag.import_errors, bag.import_errors
    return bag.dags["dbt_build"]


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def upstream_of(dag, task_id: str) -> set[str]:
    """Every task that must finish before task_id can start."""
    seen: set[str] = set()
    todo = list(dag.get_task(task_id).upstream_task_ids)
    while todo:
        current = todo.pop()
        if current not in seen:
            seen.add(current)
            todo.extend(dag.get_task(current).upstream_task_ids)
    return seen


def built(dag, node_id: str) -> str | None:
    """The task that builds a dbt model or seed (None for sources, which nothing builds)."""
    kind, _, name = node_id.split(".")
    task_id = {"model": f"build.{name}.run", "seed": f"build.{name}.seed"}.get(kind)
    return task_id if task_id in dag.task_dict else None


def test_company_tables_are_checked_against_the_screener_after_all_three_rebuild(dag) -> None:
    for table, test_name in RELATIONSHIPS.items():
        before = upstream_of(dag, f"build.{test_name}_test")
        assert {f"build.{table}.run", "build.export_screener.run"} <= before, test_name
        # Not also run early, inside the screener's or the table's own test task.
        for model in ("export_screener", table):
            excluded = dag.get_task(f"build.{model}.test").exclude or []
            assert test_name in excluded, (test_name, model)
    together = set().union(*(upstream_of(dag, f"build.{t}_test") for t in RELATIONSHIPS.values()))
    assert {f"build.{model}.run" for model in EXPORTS} <= together


def test_every_test_with_several_parents_runs_after_all_of_them_only(dag, manifest) -> None:
    wrong = []
    for node in manifest["nodes"].values():
        if node["resource_type"] != "test":
            continue
        parents = set(node["depends_on"]["nodes"])
        if len(parents) < 2:
            continue
        task_id = f"build.{node['name']}_test"
        if task_id not in dag.task_dict:
            wrong.append(f"{node['name']} has no task of its own")
            continue
        before = upstream_of(dag, task_id)
        for parent in parents:
            builder = built(dag, parent)
            if builder and builder not in before:
                wrong.append(f"{node['name']} can run before {builder}")
            own_tests = dag.task_dict.get(f"build.{parent.split('.')[-1]}.test")
            if own_tests is not None and node["name"] not in (own_tests.exclude or []):
                wrong.append(f"{node['name']} also runs inside {own_tests.task_id}")
    assert not wrong, wrong


def test_no_failing_test_can_let_the_marts_asset_update(dag) -> None:
    publish = dag.get_task("publish")
    # The Asset publish_site is scheduled on.
    assert [outlet.name for outlet in publish.outlets] == ["marts"]
    assert publish.trigger_rule == "all_success"
    before = upstream_of(dag, "publish")
    assert {f"build.{t}_test" for t in RELATIONSHIPS.values()} <= before
    # Every task of the build, so every test, must succeed before publish can run.
    build = {task_id for task_id in dag.task_dict if task_id.startswith("build.")}
    assert build - before == set(), sorted(build - before)
