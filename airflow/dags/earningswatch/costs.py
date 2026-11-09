"""What each Spark job cost: EMR Serverless reports its billed usage when a job ends.

The quarterly DAG records it in AUDIT.EMR_JOB_RUNS, beside Snowflake's own per-query credits;
dbt's mart_pipeline_costs prices both in dollars per pipeline step and Airflow run.
"""

from __future__ import annotations

EMR_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS AUDIT.EMR_JOB_RUNS ("
    "job_run_id VARCHAR, dag_id VARCHAR, run_id VARCHAR, subject VARCHAR, "
    "vcpu_hours FLOAT, memory_gb_hours FLOAT, storage_gb_hours FLOAT, "
    "job_state VARCHAR, recorded_at TIMESTAMP_NTZ)"
)


def billed_usage(job_run: dict) -> dict[str, float]:
    """vCPU-hours, memory GB-hours and storage GB-hours that EMR billed for one job run.

    EMR reports these in billedResourceUtilization once the job ends, already rounded to its
    billing rules (per second, one-minute minimum), so they price directly.
    """
    usage = job_run.get("billedResourceUtilization") or {}
    return {
        "vcpu_hours": float(usage.get("vCPUHour", 0.0)),
        "memory_gb_hours": float(usage.get("memoryGBHour", 0.0)),
        "storage_gb_hours": float(usage.get("storageGBHour", 0.0)),
    }


def record_emr_job(cursor, job_run: dict, dag_id: str, run_id: str, subject: str) -> dict:
    """Insert one job run's billed usage into AUDIT.EMR_JOB_RUNS and return it."""
    usage = billed_usage(job_run)
    cursor.execute(EMR_TABLE_SQL)
    cursor.execute(
        "INSERT INTO AUDIT.EMR_JOB_RUNS VALUES (%s, %s, %s, %s, %s, %s, %s, %s, SYSDATE())",
        (
            job_run["jobRunId"], dag_id, run_id, subject,
            usage["vcpu_hours"], usage["memory_gb_hours"], usage["storage_gb_hours"],
            job_run.get("state"),
        ),
    )  # fmt: skip
    return usage
