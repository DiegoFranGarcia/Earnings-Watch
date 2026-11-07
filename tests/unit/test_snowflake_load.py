"""Unit tests for the Snowflake RAW load: SQL, transaction order, and rollback on mismatch."""

from __future__ import annotations

import json

import boto3
import pytest
from moto import mock_aws

from earningswatch.snowflake_load import (
    NUM_COLUMNS,
    LoadMismatch,
    check_quarter,
    copy_sql,
    create_table_sql,
    expected_rows,
    load_quarter,
    quarters_to_load,
)


class FakeCursor:
    """Records statements; answers COUNT(*) with the row counts it is given."""

    def __init__(self, counts: dict[str, int], fail_on: str | None = None) -> None:
        self.counts = counts  # RAW table -> rows the transaction would hold
        self.fail_on = fail_on
        self.statements: list[str] = []
        self.params: list[tuple | None] = []
        self._last: tuple | None = None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.statements.append(sql)
        self.params.append(params)
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("simulated Snowflake error")
        if sql.startswith("SELECT COUNT(*)"):
            table = sql.split("RAW.")[1].split()[0]
            self._last = (self.counts[table],)

    def fetchone(self) -> tuple | None:
        return self._last

    def kinds(self) -> list[str]:
        return [s.split()[0] + (" " + s.split("RAW.")[1].split()[0] if "RAW." in s else "")
                for s in self.statements]  # fmt: skip


def test_only_exact_quarter_labels_reach_sql() -> None:
    assert check_quarter("2026q3") == "2026q3"
    for bad in ("2026q5", "2026Q3", "2026q3'; DROP TABLE RAW.FSDS_NUM; --", ""):
        with pytest.raises(ValueError):
            check_quarter(bad)
    with pytest.raises(ValueError):
        copy_sql("num", "2026q3' OR '1'='1")


def test_raw_table_has_silver_types_and_lineage() -> None:
    sql = create_table_sql("FSDS_NUM", NUM_COLUMNS)

    assert sql.startswith("CREATE TABLE IF NOT EXISTS RAW.FSDS_NUM (")
    assert "value NUMBER(28,4)" in sql and "ddate DATE" in sql
    for lineage in ("_source_file VARCHAR", "_source_quarter VARCHAR", "_loaded_at TIMESTAMP_NTZ"):
        assert lineage in sql


def test_copy_reads_one_partition_with_force_and_names_every_column() -> None:
    sql = copy_sql("num", "2026q3")

    assert sql.startswith("COPY INTO RAW.FSDS_NUM (")
    assert "FROM @RAW.SILVER/fsds/num/source_quarter=2026q3/)" in sql
    assert "FORCE = TRUE" in sql and "ON_ERROR = ABORT_STATEMENT" in sql
    assert "PATTERN = '.*[.]parquet'" in sql, "only Parquet: never _SUCCESS markers"
    assert '$1:"value"::NUMBER(28,4)' in sql
    targets = sql.split("(", 1)[1].split(")", 1)[0].split(", ")
    assert len(targets) == len(NUM_COLUMNS) + 3, "every silver column plus three lineage columns"


def test_a_matching_load_commits_after_checking_both_tables() -> None:
    cursor = FakeCursor({"FSDS_SUB": 6516, "FSDS_NUM": 3905397})

    result = load_quarter(cursor, "2026q3", {"sub": 6516, "num": 3905397})

    assert cursor.kinds() == [
        "BEGIN",
        "DELETE FSDS_SUB", "COPY FSDS_SUB", "SELECT FSDS_SUB",
        "DELETE FSDS_NUM", "COPY FSDS_NUM", "SELECT FSDS_NUM",
        "COMMIT",
    ]  # fmt: skip
    assert result.rows == {"sub": 6516, "num": 3905397}
    pairs = zip(cursor.statements, cursor.params, strict=True)
    deletes = [params for sql, params in pairs if sql.startswith("DELETE")]
    assert deletes == [("2026q3",), ("2026q3",)], "the quarter is a bound parameter"


def test_a_count_mismatch_rolls_back_and_never_commits() -> None:
    # The FORCE trap: COPY skips already-loaded files, so the reloaded quarter holds 0 rows.
    cursor = FakeCursor({"FSDS_SUB": 6516, "FSDS_NUM": 0})

    with pytest.raises(LoadMismatch, match="num has 0 rows, Spark wrote 3,905,397"):
        load_quarter(cursor, "2026q3", {"sub": 6516, "num": 3905397})

    assert cursor.statements[-1] == "ROLLBACK"
    assert "COMMIT" not in cursor.statements


def test_a_failing_statement_rolls_back_and_reraises() -> None:
    cursor = FakeCursor({"FSDS_SUB": 1, "FSDS_NUM": 1}, fail_on="COPY INTO RAW.FSDS_NUM")

    with pytest.raises(RuntimeError, match="simulated"):
        load_quarter(cursor, "2026q3", {"sub": 1, "num": 1})

    assert cursor.statements[-1] == "ROLLBACK"


@mock_aws
def test_expected_rows_come_from_sparks_reconciliation_record() -> None:
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="lake")
    record = {"sub": {"rows_written": 6516}, "num": {"rows_written": 3905397}}
    prefix = "silver/_reconciliation/fsds/source_quarter=2026q3/"
    s3.put_object(Bucket="lake", Key=prefix + "part-00000-abc-c000.txt", Body=json.dumps(record))
    s3.put_object(Bucket="lake", Key=prefix + "_SUCCESS", Body=b"")
    # The slice's older record sits beside the folder and must not be picked up.
    s3.put_object(Bucket="lake", Key=prefix.rstrip("/") + ".json", Body=b"{}")

    assert expected_rows(s3, "lake", "2026q3") == {"sub": 6516, "num": 3905397}

    with pytest.raises(LoadMismatch, match="found 0"):
        expected_rows(s3, "lake", "2026q2")


def test_a_manual_range_wins_over_announced_quarters() -> None:
    assert quarters_to_load("2025q4..2026q2", ["2026q3"]) == ["2025q4", "2026q1", "2026q2"]
    assert quarters_to_load("2026q3, 2026q1,2026q3", []) == ["2026q1", "2026q3"]


def test_without_a_manual_range_the_announced_quarters_load() -> None:
    assert quarters_to_load("", ["2026q3", "2026q2", "2026q3"]) == ["2026q2", "2026q3"]
    assert quarters_to_load("  ", []) == [], "nothing announced, nothing to load"


def test_bad_manual_input_is_refused() -> None:
    for bad in ("2026q3..2026q1", "2026q5", "next quarter"):
        with pytest.raises(ValueError):
            quarters_to_load(bad, [])
