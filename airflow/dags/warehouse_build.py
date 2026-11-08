"""Build the dbt project in Snowflake whenever RAW changes.

Triggered by either RAW asset (a loaded FSDS quarter or a loaded day of the daily index). Source
freshness runs first; then Cosmos renders every dbt model and seed as its own Airflow task, with
that model's tests right after it, so a failing test stops only what depends on it and a single
model can be retried. Cosmos reads the project from a pre-built manifest (target/manifest.json),
so parsing this file stays instant: rebuild the manifest with `dbt parse` after changing dbt.

The file is deliberately not named dbt_*.py: dbt imports every top-level module named dbt_* on
the Python path (its plugin discovery), and this folder is on the path in tests and in Airflow.
The DAG's id still comes from the function below: dbt_build.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.sdk import Asset, dag, task
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import LoadMode, TestBehavior

RAW_FSDS = Asset("raw_fsds")
RAW_DAILY_INDEX = Asset("raw_daily_index")
MARTS = Asset("marts")

DBT_PROJECT = Path(os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt"))
DBT_EXECUTABLE = os.environ.get("DBT_EXECUTABLE", "/opt/dbt_venv/bin/dbt")


@dag(
    schedule=(RAW_FSDS | RAW_DAILY_INDEX),  # either kind of new data rebuilds the warehouse
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(minutes=2),
        "execution_timeout": timedelta(minutes=30),
    },
    tags=["dbt", "transform"],
)
def dbt_build():
    @task.bash(env={"DBT_RUN_LABEL": "{{ run_id }}"}, append_env=True)
    def source_freshness() -> str:
        """Warn on stale RAW data; fail only past a source's error_after threshold."""
        # The project folder is read-only: dbt writes target/ and logs/ to a private scratch
        # folder instead. (Cosmos's own tasks each get a temporary copy of the project.)
        return (
            'scratch="$(mktemp -d)" && '
            f"{DBT_EXECUTABLE} source freshness"
            f" --project-dir {DBT_PROJECT} --profiles-dir {DBT_PROJECT}"
            ' --target-path "$scratch/target" --log-path "$scratch/logs"'
        )

    build = DbtTaskGroup(
        group_id="build",
        project_config=ProjectConfig(
            dbt_project_path=DBT_PROJECT,
            manifest_path=DBT_PROJECT / "target" / "manifest.json",
        ),
        profile_config=ProfileConfig(
            profile_name="earningswatch",
            target_name="dev",
            profiles_yml_filepath=DBT_PROJECT / "profiles.yml",
        ),
        execution_config=ExecutionConfig(dbt_executable_path=DBT_EXECUTABLE),
        render_config=RenderConfig(
            load_method=LoadMode.DBT_MANIFEST,
            test_behavior=TestBehavior.AFTER_EACH,
        ),
        operator_args={
            "pool": "snowflake",
            # Each task runs dbt in its own temporary copy of the project, so they never share
            # target/ or logs/. The run ID tags every Snowflake query, for cost attribution.
            "env": {"DBT_RUN_LABEL": "{{ run_id }}"},
            "append_env": True,
        },
    )

    @task(outlets=[MARTS])
    def publish() -> None:
        """Announce that the marts were rebuilt and every test passed."""

    source_freshness() >> build >> publish()


dbt_build()
