"""Save a dated copy of the SEC's ticker file every day, in bronze and silver.

The SEC keeps no history of company_tickers_exchange.json, so these daily snapshots are
the only record of ticker changes. A run only ever snapshots today's file: a run for a
past date (a backfill) is skipped, because it would file today's tickers under that date.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, task
from airflow.sdk.exceptions import AirflowSkipException

from earningswatch.callbacks import notify_failure

SILVER_COMPANY_TICKERS = Asset("silver_company_tickers")

DEFAULT_ARGS = {
    "owner": "earningswatch",
    "on_failure_callback": notify_failure,
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
    "execution_timeout": timedelta(minutes=15),
}


@dag(
    dag_id="company_tickers_snapshot",
    schedule="0 7 * * *",  # 07:00 UTC daily: the file exists every day, weekends included
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,  # past snapshots cannot be taken, so there is nothing to catch up
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["earningswatch", "ingestion"],
    doc_md=__doc__,
)
def company_tickers_snapshot():
    @task(pool="sec_api")
    def land_snapshot(**context) -> str:
        """Save today's ticker file in bronze, once per day."""
        import datetime as dt

        import boto3

        from earningswatch import company_tickers as ct
        from earningswatch.bronze import land_file
        from earningswatch.config import load_settings
        from earningswatch.sec_client import SecClient

        run_time = context.get("logical_date") or context["dag_run"].run_after
        if not ct.is_current(run_time, dt.datetime.now(dt.UTC)):
            raise AirflowSkipException(
                f"{ct.snapshot_date(run_time)} is in the past: the SEC serves only today's "
                "ticker file, so a snapshot for that day can no longer be taken"
            )
        day = ct.snapshot_date(run_time)
        settings = load_settings()
        with SecClient(settings.sec_user_agent, settings.sec_rate_per_second) as sec:
            land_file(
                sec, boto3.client("s3"), settings.company_tickers_url,
                settings.lake_bucket, ct.bronze_key(day),
            )  # fmt: skip
        return day.isoformat()

    @task(outlets=[SILVER_COMPANY_TICKERS])
    def to_silver(day_iso: str) -> int:
        """Parse the bronze snapshot into typed Parquet and replace that day's partition."""
        import datetime as dt
        import json
        import tempfile
        from pathlib import Path

        import boto3

        from earningswatch import company_tickers as ct
        from earningswatch.bronze import download_verified
        from earningswatch.config import load_settings
        from earningswatch.silver import replace_partition, write_tickers

        day = dt.date.fromisoformat(day_iso)
        settings = load_settings()
        s3 = boto3.client("s3")
        with tempfile.TemporaryDirectory(prefix="earningswatch-") as tmp:
            local = Path(tmp) / "company_tickers_exchange.json"
            download_verified(s3, settings.lake_bucket, ct.bronze_key(day), local)
            listings = ct.parse_tickers(json.loads(local.read_text(encoding="utf-8")))
            parquet = Path(tmp) / "part-0.parquet"
            rows = write_tickers(listings, parquet)
            replace_partition(s3, settings.lake_bucket, parquet, ct.silver_key(day))
        return rows

    to_silver(land_snapshot())


company_tickers_snapshot()
