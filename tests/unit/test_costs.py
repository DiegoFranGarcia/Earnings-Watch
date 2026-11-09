"""Unit tests for recording what EMR billed for a Spark job."""

from __future__ import annotations

from earningswatch.costs import billed_usage, record_emr_job

JOB_RUN = {
    "jobRunId": "00g1abc",
    "state": "SUCCESS",
    "billedResourceUtilization": {"vCPUHour": 0.511, "memoryGBHour": 2.044, "storageGBHour": 0.0},
}


def test_billed_usage_reads_emrs_own_figures() -> None:
    assert billed_usage(JOB_RUN) == {
        "vcpu_hours": 0.511, "memory_gb_hours": 2.044, "storage_gb_hours": 0.0,
    }  # fmt: skip


def test_a_job_without_billing_yet_counts_as_zero() -> None:
    assert billed_usage({"jobRunId": "x"}) == {
        "vcpu_hours": 0.0, "memory_gb_hours": 0.0, "storage_gb_hours": 0.0,
    }  # fmt: skip


def test_recording_inserts_one_row_with_the_run_it_belongs_to() -> None:
    statements: list[tuple[str, tuple | None]] = []

    class Cursor:
        def execute(self, sql: str, params: tuple | None = None) -> None:
            statements.append((sql, params))

    record_emr_job(Cursor(), JOB_RUN, "sec_fsds_quarterly", "manual__2026", "2026q3")

    assert statements[0][0].startswith("CREATE TABLE IF NOT EXISTS AUDIT.EMR_JOB_RUNS")
    insert_sql, params = statements[1]
    assert insert_sql.startswith("INSERT INTO AUDIT.EMR_JOB_RUNS")
    assert params == ("00g1abc", "sec_fsds_quarterly", "manual__2026", "2026q3",
                      0.511, 2.044, 0.0, "SUCCESS")  # fmt: skip
