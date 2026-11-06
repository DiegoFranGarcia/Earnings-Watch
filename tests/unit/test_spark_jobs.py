"""Unit tests for the EMR Serverless request the quarterly DAG sends."""

from __future__ import annotations

import pytest

from earningswatch.spark_jobs import SparkSettingsMissing, fsds_to_silver_spec

ARGS = {
    "quarter": "2026q3",
    "bronze_folder_key": "bronze/source=fsds/quarter=2026q3",
    "bucket": "lake",
    "application_id": "00ga3v42730vcc09",
    "job_role_arn": "arn:aws:iam::123456789012:role/earnings-watch-dev-spark-job",
    "code_uri": "s3://lake/artifacts/spark/93cd3fee1364/",
}


def test_spec_points_the_job_at_the_exact_bronze_folder() -> None:
    spec = fsds_to_silver_spec(**ARGS)

    submit = spec["job_driver"]["sparkSubmit"]
    assert submit["entryPoint"] == "s3://lake/artifacts/spark/93cd3fee1364/fsds_to_silver.py"
    assert submit["entryPointArguments"] == [
        "--quarter", "2026q3",
        "--bronze-folder", "s3://lake/bronze/source=fsds/quarter=2026q3",
        "--silver-root", "s3://lake/silver",
    ]  # fmt: skip
    assert submit["sparkSubmitParameters"].startswith(
        "--py-files s3://lake/artifacts/spark/93cd3fee1364/lib.zip --conf"
    )
    assert "spark.dynamicAllocation.enabled=false" in submit["sparkSubmitParameters"]
    assert spec["name"] == "fsds-to-silver-2026q3"
    logs = spec["configuration_overrides"]["monitoringConfiguration"]["s3MonitoringConfiguration"]
    assert logs["logUri"] == "s3://lake/logs/emr-serverless/"


def test_a_republished_quarter_reads_its_version_folder() -> None:
    spec = fsds_to_silver_spec(
        **ARGS | {"bronze_folder_key": "bronze/source=fsds/quarter=2026q3/version=20261115"}
    )

    arguments = spec["job_driver"]["sparkSubmit"]["entryPointArguments"]
    assert arguments[3] == "s3://lake/bronze/source=fsds/quarter=2026q3/version=20261115"


def test_missing_settings_are_named() -> None:
    with pytest.raises(SparkSettingsMissing, match="EMR_APPLICATION_ID, SPARK_CODE_URI"):
        fsds_to_silver_spec(**ARGS | {"application_id": None, "code_uri": ""})
