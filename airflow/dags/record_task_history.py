"""Copy every task attempt of the last three days from Airflow's records into Snowflake.

Airflow's metadata database already records every try of every task, including the ones a
retry recovered; this DAG reads them through Airflow's REST API (Airflow 3 keeps task code out
of that database) and merges them into AUDIT.AIRFLOW_TASK_ATTEMPTS, where dbt can report
reliability. It signs in as task-history, a user with the read-only Viewer role, and asks for a
fresh short-lived token each run.

It runs at 09:30 UTC, before the host stops at 09:45, and reads three days back, so a day the
host did not run is caught up the next time. Its own run is recorded the following day.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import dag, task

from earningswatch.callbacks import notify_failure


@dag(
    dag_id="record_task_history",
    schedule="30 9 * * *",  # 09:30 UTC: after the morning's runs, before the host stops
    start_date=pendulum.datetime(2026, 11, 20, tz="UTC"),
    catchup=False,  # each run reads three days back, so missed runs need no catching up
    max_active_runs=1,
    is_paused_upon_creation=False,
    default_args={
        "owner": "earningswatch",
        "on_failure_callback": notify_failure,
        "retries": 2,
        "retry_delay": timedelta(minutes=2),
        "execution_timeout": timedelta(minutes=10),
    },
    tags=["earningswatch", "observability"],
    doc_md=__doc__,
)
def record_task_history():
    @task(pool="snowflake")
    def record(**context) -> dict:
        """Read the attempts through the API, then merge them into AUDIT as LOADER."""
        import datetime as dt
        import os

        import requests

        from earningswatch import snowflake_load, task_history
        from earningswatch.config import load_settings

        base_url = os.environ.get("AIRFLOW_API_URL", task_history.API_URL).rstrip("/")
        user = os.environ.get("TASK_HISTORY_USER", task_history.USER)
        password = os.environ.get("TASK_HISTORY_PASSWORD", "")
        if not password:
            raise RuntimeError(
                "TASK_HISTORY_PASSWORD is not set: it comes from the airflow-internals secret "
                "(scripts/create_airflow_internals_secret.py)"
            )
        since = dt.datetime.now(dt.UTC) - task_history.LOOKBACK
        with requests.Session() as session:
            token = task_history.get_token(session, base_url, user, password)
            attempts = task_history.read_attempts(session, base_url, token, since)

        conn = snowflake_load.connect_from_settings(
            load_settings(), f"earningswatch:task_history:{context['run_id']}", schema="AUDIT"
        )
        try:
            task_history.merge_attempts(conn.cursor(), attempts)
        finally:
            conn.close()
        summary = task_history.summarize(attempts)
        print(
            f"{summary['attempts']} attempts since {since:%Y-%m-%d %H:%M} UTC: "
            f"{summary['failed_tries']} failed tries, {summary['recovered']} recovered by a retry"
        )
        return summary

    record()


record_task_history()
