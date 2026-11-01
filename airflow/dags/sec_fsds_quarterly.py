"""Land each quarter's Financial Statement Data Set in bronze, once the SEC publishes it.

A run starts on the first day of a quarter and collects the quarter that just ended.
It waits (deferred, holding nothing) until the SEC publishes the ZIP, lands it with a
manifest, then extracts sub, num, tag and pre beside it. A quarter the SEC republishes
is kept under a version= folder beside the original and flagged for reprocessing.
Converting to silver Parquet is Stage 2 (Spark on EMR).
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.sdk import Asset, dag, task

from earningswatch.sensors import SecFileSensor

BRONZE_FSDS = Asset("bronze_fsds")

DEFAULT_ARGS = {
    "owner": "earningswatch",
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
    "execution_timeout": timedelta(minutes=15),
}


@dag(
    dag_id="sec_fsds_quarterly",
    schedule="0 8 1 1,4,7,10 *",  # 08:00 UTC on the first day of each quarter
    start_date=pendulum.datetime(2009, 7, 1, tz="UTC"),  # its first run collects 2009q2
    catchup=False,  # history is loaded deliberately with `airflow backfill create`
    max_active_runs=2,
    default_args=DEFAULT_ARGS,
    tags=["earningswatch", "ingestion"],
    doc_md=__doc__,
)
def sec_fsds_quarterly():
    @task
    def which_quarter(**context) -> dict:
        """The quarter this run collects: the one before its logical date's quarter."""
        import datetime as dt

        from earningswatch import fsds
        from earningswatch.config import load_settings

        run_time = context.get("logical_date") or context["dag_run"].run_after
        quarter = fsds.previous_quarter(run_time.astimezone(dt.UTC).date())
        return {"quarter": quarter, "zip_url": fsds.zip_url(quarter, load_settings().fsds_base_url)}

    target = which_quarter()

    wait_for_zip = SecFileSensor(
        task_id="wait_for_zip",
        url="{{ ti.xcom_pull(task_ids='which_quarter')['zip_url'] }}",
        pool="sec_api",
        poll_interval=timedelta(hours=6),
        max_wait=timedelta(days=45),
        # A deferred task's deadline is start_date + execution_timeout, so the default
        # 15 minutes would cut the first 6-hour sleep short. Let max_wait decide instead.
        execution_timeout=timedelta(days=46),
    )

    @task(pool="sec_api", execution_timeout=timedelta(hours=1))
    def land_zip(target: dict) -> dict:
        """Land the ZIP in bronze, or confirm it is already there and unchanged."""
        import datetime as dt
        from dataclasses import asdict

        import boto3

        from earningswatch.config import load_settings
        from earningswatch.quarterly import land_quarter
        from earningswatch.sec_client import SecClient

        settings = load_settings()
        with SecClient(settings.sec_user_agent, settings.sec_rate_per_second) as sec:
            landing = land_quarter(
                sec, boto3.client("s3"), settings.lake_bucket, target["quarter"],
                settings.fsds_base_url, dt.datetime.now(dt.UTC).date(),
            )  # fmt: skip
        return asdict(landing)

    @task(outlets=[BRONZE_FSDS], execution_timeout=timedelta(hours=2))
    def extract(landing: dict) -> dict:
        """Unzip sub, num, tag and pre beside the ZIP; return each file's data rows."""
        import logging

        import boto3

        from earningswatch import fsds
        from earningswatch.bronze import extract_zip
        from earningswatch.config import load_settings

        if landing["republished"]:
            logging.getLogger(__name__).warning(
                "%s was republished by the SEC; reprocess it from %s",
                landing["quarter"],
                landing["zip_key"],
            )
        settings = load_settings()
        results = extract_zip(
            boto3.client("s3"), settings.lake_bucket, landing["zip_key"], fsds.FSDS_MEMBERS
        )
        return {r.member: (r.manifest.line_count or 1) - 1 for r in results}

    landed = land_zip(target)
    wait_for_zip >> landed
    target >> wait_for_zip
    extract(landed)


sec_fsds_quarterly()
