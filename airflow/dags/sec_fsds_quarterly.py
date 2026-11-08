"""Land each quarter's Financial Statement Data Set in bronze, once the SEC publishes it.

A run starts on the first day of a quarter and collects the quarter that just ended.
It waits (deferred, holding nothing) until the SEC publishes the ZIP, lands it with a
manifest, then extracts sub, num, tag and pre beside it. A quarter the SEC republishes
is kept under a version= folder beside the original and flagged for reprocessing.
Finally, Spark on EMR Serverless converts the quarter's exact bronze folder to silver Parquet.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.amazon.aws.operators.emr import EmrServerlessStartJobOperator
from airflow.sdk import Asset, dag, task

from earningswatch.callbacks import notify_failure
from earningswatch.sensors import SecFileSensor

BRONZE_FSDS = Asset("bronze_fsds")
SILVER_FSDS = Asset("silver_fsds")

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

    @task(multiple_outputs=True)
    def spark_job_spec(landing: dict) -> dict:
        """The EMR request to convert exactly the bronze folder land_zip chose."""
        from earningswatch.config import load_settings
        from earningswatch.spark_jobs import fsds_to_silver_spec

        settings = load_settings()
        return fsds_to_silver_spec(
            quarter=landing["quarter"],
            bronze_folder_key=landing["zip_key"].rsplit("/", 1)[0],
            bucket=settings.lake_bucket,
            application_id=settings.emr_application_id,
            job_role_arn=settings.emr_job_role_arn,
            code_uri=settings.spark_code_uri,
        )

    landed = land_zip(target)
    wait_for_zip >> landed
    target >> wait_for_zip
    extracted = extract(landed)
    spec = spark_job_spec(landed)
    extracted >> spec

    to_silver = EmrServerlessStartJobOperator(
        task_id="to_silver",
        application_id=spec["application_id"],
        execution_role_arn=spec["execution_role_arn"],
        job_driver=spec["job_driver"],
        configuration_overrides=spec["configuration_overrides"],
        name=spec["name"],
        config={"executionTimeoutMinutes": 60},  # EMR stops the job itself after an hour
        aws_conn_id=None,  # the default AWS credentials: aws login locally, a role on EC2
        region_name="us-east-1",
        deferrable=True,  # wait in the triggerer, holding no worker
        waiter_delay=60,
        waiter_max_attempts=120,  # check every minute, for up to two hours
        pool="emr",  # one Spark job at a time; the pool counts deferred tasks
        # A deferred task's deadline is start_date + execution_timeout: keep it above the wait.
        execution_timeout=timedelta(hours=3),
    )

    @task(outlets=[SILVER_FSDS])
    def announce_silver(landing: dict, **context) -> None:
        """Tell downstream DAGs which quarter is new in silver (snowflake_load reads it)."""
        context["outlet_events"][SILVER_FSDS].extra = {"quarter": landing["quarter"]}

    to_silver >> announce_silver(landed)


sec_fsds_quarterly()
