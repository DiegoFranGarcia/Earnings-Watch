"""Fetch EDGAR's daily index every morning: land it in bronze, then parse it into silver.

Each run handles the calendar day before its logical date (see earningswatch.daily_index).
Weekends and federal holidays are skipped. A business day whose index is not published yet
is retried for a few hours; one still missing days later is skipped, because EDGAR never
published it (for example, an unscheduled closure).
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, task
from airflow.sdk.exceptions import AirflowSkipException

SILVER_DAILY_INDEX = Asset("silver_daily_index")

DEFAULT_ARGS = {
    "owner": "earningswatch",
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
    "execution_timeout": timedelta(minutes=15),
}


@dag(
    dag_id="sec_daily_index",
    schedule="0 6 * * *",  # 06:00 UTC: after EDGAR builds the index (from about 22:00 ET)
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,  # history is loaded deliberately with `airflow backfill create`
    max_active_runs=2,
    default_args=DEFAULT_ARGS,
    tags=["earningswatch", "ingestion"],
    doc_md=__doc__,
)
def sec_daily_index():
    # Imports live inside tasks: Airflow re-reads this file every few minutes, so module
    # level stays cheap.

    @task(pool="sec_api", retries=8, retry_delay=timedelta(minutes=30))
    def land_index(**context) -> str:
        """Land the day's index in bronze, unless it is already there or cannot exist."""
        import datetime as dt

        import boto3

        from earningswatch import daily_index as di
        from earningswatch.bronze import land_file, read_manifest
        from earningswatch.config import load_settings
        from earningswatch.sec_client import SecClient, SecNotFoundError

        run_time = context.get("logical_date") or context["dag_run"].run_after
        day = di.target_date(run_time)
        if not di.is_business_day(day):
            raise AirflowSkipException(f"{day} is a weekend or federal holiday: no index exists")

        settings = load_settings()
        s3 = boto3.client("s3")
        key = di.bronze_key(day)
        if read_manifest(s3, settings.lake_bucket, key) is not None:
            return day.isoformat()  # already landed: no request to the SEC at all

        with SecClient(settings.sec_user_agent, settings.sec_rate_per_second) as sec:
            try:
                listing = sec.get_json(di.quarter_folder_url(day) + "index.json")
            except SecNotFoundError:
                listing = {}  # a new quarter's folder may not exist yet
            if di.file_name(day) not in di.published_files(listing):
                # The clock decides only whether to keep waiting, never which day to fetch.
                if di.missing_is_final(day, dt.datetime.now(dt.UTC)):
                    raise AirflowSkipException(f"EDGAR published no index for {day}")
                raise FileNotFoundError(f"{di.file_name(day)} is not published yet; will retry")
            land_file(sec, s3, di.file_url(day), settings.lake_bucket, key)
        return day.isoformat()

    @task(outlets=[SILVER_DAILY_INDEX])
    def to_silver(day_iso: str, **context) -> int:
        """Parse the bronze file into typed Parquet and replace that day's silver partition."""
        import datetime as dt
        import tempfile
        from pathlib import Path

        import boto3

        from earningswatch import daily_index as di
        from earningswatch.bronze import download_verified
        from earningswatch.config import load_settings
        from earningswatch.silver import replace_partition, write_filings

        day = dt.date.fromisoformat(day_iso)
        settings = load_settings()
        s3 = boto3.client("s3")
        with tempfile.TemporaryDirectory(prefix="earningswatch-") as tmp:
            local = Path(tmp) / di.file_name(day)
            download_verified(s3, settings.lake_bucket, di.bronze_key(day), local)
            with local.open(encoding="utf-8") as handle:
                filings = di.parse_master_index(handle)
            parquet = Path(tmp) / "part-0.parquet"
            rows = write_filings(filings, parquet)
            replace_partition(s3, settings.lake_bucket, parquet, di.silver_key(day))
        # Tell downstream DAGs which day is new in silver (snowflake_load_daily_index reads it).
        context["outlet_events"][SILVER_DAILY_INDEX].extra = {"day": day_iso}
        return rows

    to_silver(land_index())


sec_daily_index()
