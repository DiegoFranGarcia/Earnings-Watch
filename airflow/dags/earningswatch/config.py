"""Settings read from the environment, so no email, bucket or account ID lives in code."""

from __future__ import annotations

import os
from dataclasses import dataclass

from earningswatch.company_tickers import COMPANY_TICKERS_URL
from earningswatch.fsds import FSDS_BASE_URL


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str
    lake_bucket: str
    sec_rate_per_second: float
    fsds_base_url: str
    company_tickers_url: str
    # Where Spark runs; optional, so DAGs that do not use EMR need none of them.
    emr_application_id: str | None = None
    emr_job_role_arn: str | None = None
    spark_code_uri: str | None = None  # s3://<lake>/artifacts/spark/<commit>
    # Snowflake, as SVC_AIRFLOW (role LOADER); optional, like the EMR settings.
    sf_account: str | None = None  # ORG-ACCOUNT
    sf_user: str | None = None
    sf_private_key_path: str | None = None
    sf_database: str | None = None


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Environment variable {name} is not set. Add it to airflow/.env "
            "(see airflow/.env.example)."
        )
    return value


def load_settings() -> Settings:
    """Read settings at call time, never at import time, so DAG parsing stays cheap."""
    return Settings(
        sec_user_agent=_required("SEC_USER_AGENT"),
        lake_bucket=_required("LAKE_BUCKET"),
        sec_rate_per_second=float(os.environ.get("SEC_RATE_PER_SECOND", "5")),
        # The SEC has moved this path before, so it can be overridden without a code change.
        fsds_base_url=os.environ.get("FSDS_BASE_URL", FSDS_BASE_URL),
        # The SEC moved this file once already (from /data/ to /files/).
        company_tickers_url=os.environ.get("COMPANY_TICKERS_URL", COMPANY_TICKERS_URL),
        emr_application_id=os.environ.get("EMR_APPLICATION_ID") or None,
        emr_job_role_arn=os.environ.get("EMR_JOB_ROLE_ARN") or None,
        spark_code_uri=os.environ.get("SPARK_CODE_URI") or None,
        sf_account=os.environ.get("SF_ACCOUNT") or None,
        sf_user=os.environ.get("SF_USER") or None,
        sf_private_key_path=os.environ.get("SF_PRIVATE_KEY_PATH") or None,
        sf_database=os.environ.get("SF_DATABASE") or None,
    )
