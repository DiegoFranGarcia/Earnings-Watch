"""The EMR Serverless request for the FSDS-to-silver Spark job, built as plain data.

Kept out of the DAG so it can be unit-tested: the DAG only passes this to the operator.
"""

from __future__ import annotations

# A fixed, predictable cluster: a driver and two executors of 4 vCPU and about 16 GB each
# (14 GB plus EMR's overhead). Dynamic allocation off, so cost and benchmarks are comparable.
SPARK_CONF = (
    "--conf spark.dynamicAllocation.enabled=false",
    "--conf spark.executor.instances=2",
    "--conf spark.executor.cores=4",
    "--conf spark.executor.memory=14g",
    "--conf spark.driver.cores=4",
    "--conf spark.driver.memory=14g",
)


class SparkSettingsMissing(RuntimeError):
    """EMR is not configured for this Airflow."""


def fsds_to_silver_spec(
    *,
    quarter: str,
    bronze_folder_key: str,
    bucket: str,
    application_id: str | None,
    job_role_arn: str | None,
    code_uri: str | None,
) -> dict:
    """Everything StartJobRun needs to convert one quarter, from its exact bronze folder."""
    missing = [
        name
        for name, value in (
            ("EMR_APPLICATION_ID", application_id),
            ("EMR_JOB_ROLE_ARN", job_role_arn),
            ("SPARK_CODE_URI", code_uri),
        )
        if not value
    ]
    if missing:
        raise SparkSettingsMissing(f"set {', '.join(missing)} in airflow/.env")
    code = code_uri.rstrip("/")
    return {
        "application_id": application_id,
        "execution_role_arn": job_role_arn,
        "name": f"fsds-to-silver-{quarter}",
        "job_driver": {
            "sparkSubmit": {
                "entryPoint": f"{code}/fsds_to_silver.py",
                "entryPointArguments": [
                    "--quarter",
                    quarter,
                    "--bronze-folder",
                    f"s3://{bucket}/{bronze_folder_key.strip('/')}",
                    "--silver-root",
                    f"s3://{bucket}/silver",
                ],  # fmt: skip
                "sparkSubmitParameters": " ".join((f"--py-files {code}/lib.zip", *SPARK_CONF)),
            }
        },
        "configuration_overrides": {
            "monitoringConfiguration": {
                "s3MonitoringConfiguration": {"logUri": f"s3://{bucket}/logs/emr-serverless/"}
            }
        },
    }
