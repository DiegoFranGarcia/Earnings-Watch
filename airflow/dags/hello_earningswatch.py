"""Stage 0 smoke test: proves the EarningsWatch Airflow image works.

Checks that the Amazon and Snowflake providers import and that dbt runs from
its own virtual environment. Trigger it by hand; it has no schedule.
"""

from __future__ import annotations

import subprocess
from datetime import timedelta

import pendulum
from airflow.sdk import dag, task

from earningswatch.callbacks import notify_failure

DBT_BIN = "/opt/dbt_venv/bin/dbt"

# House rules every EarningsWatch DAG follows.
DEFAULT_ARGS = {
    "owner": "earningswatch",
    "on_failure_callback": notify_failure,
    "retries": 1,
    "retry_delay": timedelta(minutes=1),
    "execution_timeout": timedelta(minutes=5),
}


@dag(
    dag_id="hello_earningswatch",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    default_args=DEFAULT_ARGS,
    tags=["earningswatch", "stage-0"],
    doc_md=__doc__,
)
def hello_earningswatch():
    @task
    def check_providers() -> dict[str, str]:
        # Imported inside the task: top-level code runs on every DAG parse.
        from importlib.metadata import version

        packages = [
            "apache-airflow",
            "apache-airflow-providers-amazon",
            "apache-airflow-providers-snowflake",
        ]
        found = {pkg: version(pkg) for pkg in packages}
        for pkg, ver in found.items():
            print(f"{pkg}=={ver}")
        return found

    @task
    def check_dbt() -> str:
        result = subprocess.run(  # noqa: S603 - fixed path, no user input
            [DBT_BIN, "--version"], capture_output=True, text=True, check=True
        )
        print(result.stdout)
        return next(line.strip() for line in result.stdout.splitlines() if "installed" in line)

    @task
    def say_hello(providers: dict[str, str], dbt: str) -> None:
        airflow_version = providers["apache-airflow"]
        print(f"EarningsWatch is alive on Airflow {airflow_version}. dbt {dbt}.")

    say_hello(check_providers(), check_dbt())


hello_earningswatch()
