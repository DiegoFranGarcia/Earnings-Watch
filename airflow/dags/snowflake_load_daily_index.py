"""Load EDGAR's daily index into Snowflake RAW, triggered by new silver data.

Runs when sec_daily_index announces silver_daily_index (the event names its day), or by hand
with a month range: {"months": "2025-01..2026-11"}. Each month is one task and one transaction,
replacing the whole month and committing only if RAW holds exactly the rows its silver files
contain. A new day therefore reloads its month: a few seconds, and always exact.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, Param, dag, get_current_context, task
from airflow.sdk.exceptions import AirflowFailException

SILVER_DAILY_INDEX = Asset("silver_daily_index")
RAW_DAILY_INDEX = Asset("raw_daily_index")


def _connect(query_tag: str):
    from earningswatch.config import load_settings
    from earningswatch.snowflake_load import SnowflakeSettingsMissing, connect_from_settings

    try:
        return connect_from_settings(load_settings(), query_tag)
    except SnowflakeSettingsMissing as exc:
        raise AirflowFailException(str(exc)) from exc  # configuration: retrying cannot help


@dag(
    schedule=[SILVER_DAILY_INDEX],
    start_date=pendulum.datetime(2026, 11, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 2,  # for connection hiccups; count mismatches fail immediately
        "retry_delay": timedelta(minutes=2),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=20),
    },
    params={
        "months": Param(
            "",
            type="string",
            description="Manual runs: '2026-11' or '2025-01..2026-11'. Empty: load the months "
            "of the days silver_daily_index announced.",
        )
    },
    tags=["snowflake", "load"],
)
def snowflake_load_daily_index():
    @task(execution_timeout=timedelta(minutes=5))
    def which_months(**context) -> list[str]:
        from earningswatch.snowflake_load import months_to_load

        events = context["triggering_asset_events"].get(SILVER_DAILY_INDEX, [])
        announced = [e.extra["day"] for e in events if e.extra.get("day")]
        months = months_to_load(context["params"]["months"], announced)
        print(f"Months to load: {months or 'none'}")
        return months

    @task(execution_timeout=timedelta(minutes=5))
    def ensure_table(**context) -> None:
        from earningswatch.snowflake_load import daily_index_table_sql

        con = _connect(f"earningswatch:load:{context['run_id']}")
        try:
            con.cursor().execute(daily_index_table_sql())
        finally:
            con.close()

    @task(
        pool="snowflake",
        max_active_tis_per_dagrun=1,  # each load holds a transaction on the same table
        map_index_template="{{ month }}",
        execution_timeout=timedelta(minutes=30),
        outlets=[RAW_DAILY_INDEX],
    )
    def load(month: str) -> int:
        from earningswatch.snowflake_load import LoadMismatch, load_daily_index_month

        context = get_current_context()
        context["month"] = month  # read by map_index_template
        con = _connect(f"earningswatch:load:{context['run_id']}")
        try:
            return load_daily_index_month(con.cursor(), month)
        except LoadMismatch as exc:
            # Deterministic: retrying would only delay the alert. RAW was rolled back.
            raise AirflowFailException(str(exc)) from exc
        finally:
            con.close()

    months = which_months()
    months >> ensure_table() >> load.expand(month=months)


snowflake_load_daily_index()
