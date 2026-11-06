"""Parity: the Spark job must reproduce the slice's DuckDB converter exactly.

Both run on the same awkward quarter (quoted tabs, an exact duplicate, a key conflict, an
empty value, a bad value, a malformed line, and a number with no filing). The outputs must
have the same columns, the same types and the same rows, and the reconciliations must agree.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import duckdb
import pytest
from fsds_fixtures import awkward_quarter

from compare_silver import compare
from fsds_to_parquet import convert, write_parquet
from jobs.fsds_to_silver import ReconciliationError, run, verify_partition

QUARTER = "2026q3"


def _expected(folder, name: str) -> int:
    return json.loads((folder / f"{name}.manifest.json").read_text())["line_count"] - 1


def test_spark_matches_duckdb_on_an_awkward_quarter(spark, tmp_path) -> None:
    bronze = tmp_path / "bronze"
    folder = awkward_quarter(bronze)

    con = duckdb.connect()
    duck = convert(con, folder / "sub.txt", folder / "num.txt",
                   _expected(folder, "sub.txt"), _expected(folder, "num.txt"),
                   quarantine_limit=1.0)  # fmt: skip
    write_parquet(con, tmp_path / "duck", QUARTER)
    sparks = run(spark, QUARTER, str(bronze), str(tmp_path / "spark"), quarantine_limit=1.0)

    assert compare(str(tmp_path / "duck"), str(tmp_path / "spark"), QUARTER) == []
    for table in ("sub", "num"):
        assert asdict(getattr(sparks, table)) == asdict(getattr(duck, table)), table
    assert sparks.num_rows_without_filing == duck.num_rows_without_filing == 1
    assert sparks.keys_with_conflicting_values == duck.keys_with_conflicting_values == 1
    assert sparks.rows_with_conflicting_values == duck.rows_with_conflicting_values == 2
    assert (sparks.num.rows_quarantined, sparks.num.cast_failures) == (1, 1)
    assert sparks.num.duplicates_removed == 1


def test_rerunning_a_quarter_replaces_only_its_partition(spark, tmp_path) -> None:
    bronze, silver = tmp_path / "bronze", tmp_path / "silver"
    awkward_quarter(bronze)
    other = silver / "fsds" / "num" / "source_quarter=2026q2"
    other.mkdir(parents=True)
    (other / "keep-me.parquet").write_bytes(b"another quarter's file")

    for _ in range(2):  # the same quarter, twice
        run(spark, QUARTER, str(bronze), str(silver), quarantine_limit=1.0)

    partition = silver / "fsds" / "num" / f"source_quarter={QUARTER}"
    assert len(list(partition.glob("*.parquet"))) == 1, "one file per quarter, not one per run"
    assert (other / "keep-me.parquet").exists(), "other quarters are untouched"


def test_too_many_bad_rows_fails_before_writing(spark, tmp_path) -> None:
    bronze, silver = tmp_path / "bronze", tmp_path / "silver"
    awkward_quarter(bronze)

    with pytest.raises(ReconciliationError, match="limit"):
        run(spark, QUARTER, str(bronze), str(silver))  # default limit: 0.01%

    assert not (silver / "fsds").exists(), "nothing is written when reconciliation fails"


def test_verify_partition_catches_output_that_never_landed(spark, tmp_path) -> None:
    table = tmp_path / "silver" / "fsds" / "num"
    (table / f"source_quarter={QUARTER}").mkdir(parents=True)  # written "successfully", empty

    with pytest.raises(ReconciliationError, match="no readable Parquet"):
        verify_partition(spark, str(table), QUARTER, expected=3)


def test_verify_partition_catches_a_row_count_mismatch(spark, tmp_path) -> None:
    table = tmp_path / "silver" / "fsds" / "num"
    spark.range(2).write.parquet(str(table / f"source_quarter={QUARTER}"))

    with pytest.raises(ReconciliationError, match="wrote 3 rows, but 2 are readable"):
        verify_partition(spark, str(table), QUARTER, expected=3)
    verify_partition(spark, str(table), QUARTER, expected=2)  # the right count passes
