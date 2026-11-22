"""Fetch EDGAR's daily index every morning: land it in bronze, then parse it into silver.

Each run handles the calendar day before its logical date (see earningswatch.daily_index).
Weekends and federal holidays are skipped. A business day whose index is not published yet
is retried for a few hours; one still missing days later is skipped, because EDGAR never
published it (for example, an unscheduled closure).

Each morning, check_landed_days also confirms that every business day of the last four weeks
has its index in bronze, and fails (alerting) while one does not: a run that failed for good,
as on 2026-11-06, leaves its day missing, because later runs each fetch only their own day.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, task
from airflow.sdk.definitions.deadline import AsyncCallback, DeadlineAlert, DeadlineReference
from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException

from earningswatch.callbacks import notify_failure

SILVER_DAILY_INDEX = Asset("silver_daily_index")

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
    dag_id="sec_daily_index",
    schedule="0 6 * * *",  # 06:00 UTC: after EDGAR builds the index (from about 22:00 ET)
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,  # history is loaded deliberately with `airflow backfill create`
    max_active_runs=2,
    default_args=DEFAULT_ARGS,
    # Finished by 09:00 UTC (06:00 + 3 h), or an alert: catches a run that is stuck or never
    # started, which no failure callback would report. Before the host's scheduled stop (09:45).
    deadline=DeadlineAlert(
        reference=DeadlineReference.DAGRUN_LOGICAL_DATE,
        interval=timedelta(hours=3),
        callback=AsyncCallback(
            "earningswatch.callbacks.notify_deadline_missed",
            kwargs={"dag_id": "sec_daily_index", "deadline": "09:00 UTC"},
        ),
    ),
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

    @task(retries=0, execution_timeout=timedelta(minutes=5), trigger_rule="all_done")
    def check_landed_days() -> int:
        """Fail, alerting, while a recent business day has no index in bronze.

        Runs whatever happened to today's landing. Only reads S3 (one listing), never the SEC,
        and has no outlet: a gap in an earlier day never holds back today's data.
        """
        import datetime as dt
        import os
        from pathlib import Path

        import boto3

        from earningswatch import daily_index as di
        from earningswatch.config import load_settings

        days = di.days_to_check(dt.datetime.now(dt.UTC))
        if not days:
            return 0
        dbt_project = Path(os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt"))
        closed = di.read_closed_days(dbt_project / "seeds" / "sec_closed_days.csv")
        prefix = "bronze/source=daily_index/"
        keys: set[str] = set()
        paginator = boto3.client("s3").get_paginator("list_objects_v2")
        start = f"{prefix}date={days[0]:%Y-%m-%d}"  # every key of that day sorts after this
        bucket = load_settings().lake_bucket
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix, StartAfter=start):
            keys.update(obj["Key"] for obj in page.get("Contents", []))
        missing = di.missing_days(days, keys, closed)
        if missing:
            raise AirflowFailException(di.describe_missing(missing))
        print(f"All {len(days)} business days from {days[0]} to {days[-1]} have their index.")
        return len(days)

    to_silver(land_index()) >> check_landed_days()


sec_daily_index()
