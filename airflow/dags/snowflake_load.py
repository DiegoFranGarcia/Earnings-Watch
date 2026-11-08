"""Load silver FSDS quarters into Snowflake RAW, triggered by new silver data.

Runs when sec_fsds_quarterly announces silver_fsds (the event names its quarter), or by hand
with a quarter range: {"quarters": "2009q2..2026q3"} loads the full history. Each quarter is
its own task and its own transaction, committed only if Snowflake's row counts equal Spark's
reconciliation record.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, Param, dag, get_current_context, task
from airflow.sdk.exceptions import AirflowFailException

from earningswatch.callbacks import notify_failure

SILVER_FSDS = Asset("silver_fsds")
RAW_FSDS = Asset("raw_fsds")


def _connect(query_tag: str):
    from earningswatch.config import load_settings
    from earningswatch.snowflake_load import SnowflakeSettingsMissing, connect_from_settings

    try:
        return connect_from_settings(load_settings(), query_tag)
    except SnowflakeSettingsMissing as exc:
        raise AirflowFailException(str(exc)) from exc  # configuration: retrying cannot help


@dag(
    schedule=[SILVER_FSDS],
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "owner": "earningswatch",
        "on_failure_callback": notify_failure,
        "retries": 2,  # for connection hiccups; count mismatches fail immediately
        "retry_delay": timedelta(minutes=2),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=20),
    },
    params={
        "quarters": Param(
            "",
            type="string",
            description="Manual runs: '2026q3' or '2009q2..2026q3'. Empty: load what "
            "silver_fsds announced.",
        )
    },
    tags=["snowflake", "load"],
)
def snowflake_load():
    @task(execution_timeout=timedelta(minutes=5))
    def which_quarters(**context) -> list[str]:
        from earningswatch.snowflake_load import quarters_to_load

        events = context["triggering_asset_events"].get(SILVER_FSDS, [])
        announced = [e.extra["quarter"] for e in events if e.extra.get("quarter")]
        try:
            quarters = quarters_to_load(context["params"]["quarters"], announced)
        except ValueError as exc:
            raise AirflowFailException(f"bad quarters parameter: {exc}") from exc  # a typo
        print(f"Quarters to load: {quarters or 'none'}")
        return quarters

    @task(execution_timeout=timedelta(minutes=5))
    def ensure_tables(**context) -> None:
        from earningswatch.snowflake_load import TABLES, create_table_sql

        con = _connect(f"earningswatch:load:{context['run_id']}")
        try:
            cur = con.cursor()
            for table, columns in TABLES.values():
                cur.execute(create_table_sql(table, columns))
        finally:
            con.close()

    @task(
        pool="snowflake",
        max_active_tis_per_dagrun=1,  # each load holds a transaction on the same two tables
        map_index_template="{{ quarter }}",  # label each mapped task with its quarter in the UI
        execution_timeout=timedelta(minutes=30),
        outlets=[RAW_FSDS],
    )
    def load(quarter: str) -> dict[str, int]:
        import boto3

        from earningswatch.config import load_settings
        from earningswatch.snowflake_load import LoadMismatch, expected_rows, load_quarter

        context = get_current_context()
        context["quarter"] = quarter  # read by map_index_template
        con = _connect(f"earningswatch:load:{context['run_id']}")
        try:
            expected = expected_rows(boto3.client("s3"), load_settings().lake_bucket, quarter)
            return load_quarter(con.cursor(), quarter, expected).rows
        except LoadMismatch as exc:
            # Deterministic: retrying would only delay the alert. RAW was rolled back.
            raise AirflowFailException(str(exc)) from exc
        finally:
            con.close()

    quarters = which_quarters()
    quarters >> ensure_tables() >> load.expand(quarter=quarters)


snowflake_load()
