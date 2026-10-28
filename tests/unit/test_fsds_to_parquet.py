"""Unit tests for the slice's DuckDB converter, on tiny files with the real FSDS layout."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from fsds_to_parquet import (
    NUM_COLUMNS,
    SUB_COLUMNS,
    ReconciliationError,
    convert,
    write_parquet,
    write_quarantine,
)

ADSH = "0000002488-26-000123"


def _tsv(path: Path, columns: tuple[str, ...], rows: list[dict[str, str]]) -> Path:
    lines = ["\t".join(columns)] + ["\t".join(row.get(c, "") for c in columns) for row in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def _sub_row(**overrides: str) -> dict[str, str]:
    row = {
        "adsh": ADSH, "cik": "2488", "name": "ADVANCED MICRO DEVICES INC", "sic": "3674",
        "afs": "1-LAF", "wksi": "0", "fye": "1231", "form": "10-Q", "period": "20260630",
        "fy": "2026", "fp": "Q2", "filed": "20260805", "accepted": "2026-08-04 17:40:00.0",
        "prevrpt": "0", "detail": "1", "nciks": "1",
    }  # fmt: skip
    return row | overrides


def _num_row(**overrides: str) -> dict[str, str]:
    row = {
        "adsh": ADSH, "tag": "NetIncomeLoss", "version": "us-gaap/2026", "ddate": "20260630",
        "qtrs": "2", "uom": "USD", "value": "1234000000.0000",
    }  # fmt: skip
    return row | overrides


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect()


def _convert(con, tmp_path, sub_rows, num_rows, **kwargs):
    sub = _tsv(tmp_path / "sub.txt", SUB_COLUMNS, sub_rows)
    num = _tsv(tmp_path / "num.txt", NUM_COLUMNS, num_rows)
    expected_sub = kwargs.pop("expected_sub", len(sub_rows))
    expected_num = kwargs.pop("expected_num", len(num_rows))
    return convert(con, sub, num, expected_sub, expected_num, **kwargs)


def test_columns_get_real_types(con, tmp_path) -> None:
    _convert(con, tmp_path, [_sub_row()], [_num_row()])

    cik, period, accepted, prevrpt, fye = con.execute(
        "SELECT cik, period, accepted, prevrpt, fye FROM sub"
    ).fetchone()
    assert (cik, period, prevrpt, fye) == (2488, dt.date(2026, 6, 30), False, "1231")
    # The SEC gives no timezone, so this stays a naive timestamp (EDGAR runs on Eastern time).
    assert accepted.isoformat() == "2026-08-04T17:40:00"
    num = con.execute("SELECT ddate, qtrs, value FROM num").fetchone()
    assert num == (dt.date(2026, 6, 30), 2, Decimal("1234000000.0000"))


def test_num_is_enriched_from_sub(con, tmp_path) -> None:
    _convert(con, tmp_path, [_sub_row()], [_num_row()])

    row = con.execute("SELECT cik, form, filed, fy, fp FROM num").fetchone()
    assert row == (2488, "10-Q", dt.date(2026, 8, 5), 2026, "Q2")


def test_entity_totals_and_period_types(con, tmp_path) -> None:
    rows = [
        _num_row(),
        _num_row(segments="BusinessSegments=DataCenter;"),
        _num_row(tag="Assets", qtrs="0"),
    ]
    _convert(con, tmp_path, [_sub_row()], rows)

    result = con.execute(
        "SELECT tag, segments IS NULL, is_entity_total, period_type FROM num ORDER BY tag, 2"
    ).fetchall()
    assert result == [
        ("Assets", True, True, "instant"),
        ("NetIncomeLoss", False, False, "duration"),
        ("NetIncomeLoss", True, True, "duration"),
    ]


def test_exact_duplicates_are_removed_and_counted(con, tmp_path) -> None:
    rows = [_num_row(), _num_row(), _num_row(tag="Assets", qtrs="0")]

    rec = _convert(con, tmp_path, [_sub_row()], rows)

    assert rec.num.duplicates_removed == 1
    assert rec.num.rows_written == 2
    assert rec.keys_with_conflicting_values == 0
    assert con.execute("SELECT bool_or(has_key_conflict) FROM num").fetchone()[0] is False


def test_conflicting_values_are_kept_and_flagged(con, tmp_path) -> None:
    rows = [_num_row(value="1.0000"), _num_row(value="2.0000"), _num_row(tag="Assets", qtrs="0")]

    rec = _convert(con, tmp_path, [_sub_row()], rows)

    assert rec.num.duplicates_removed == 0, "different values are not duplicates"
    assert rec.keys_with_conflicting_values == 1
    assert rec.rows_with_conflicting_values == 2
    flagged = con.execute("SELECT value FROM num WHERE has_key_conflict ORDER BY value").fetchall()
    assert flagged == [(Decimal("1.0000"),), (Decimal("2.0000"),)]


# -- the SEC quotes fields that contain tabs ------------------------------------

QUOTED_ROWS = (
    # One tab inside the quotes and an empty footnote: with quoting off, this row was
    # silently accepted with its columns shifted (value empty, number in footnote).
    "{adsh}\tInvestmentOwnedAtCost\tus-gaap/2026\t20251231\t0\tUSD\t"
    '"InvestmentIdentifier=Lafayette Square Mortgage Solutions, LLC\t | Equity;"'
    "\t\t300000.0000\t\n"
    # Two tabs and a footnote: with quoting off, this row was rejected.
    "{adsh}\tInvestmentOwnedAtFairValue\tus-gaap/2026\t20251231\t0\tUSD\t"
    '"InvestmentIdentifier=NC Ocala Co-Invest Beta, LP\t | Aerospace\t & Defense;"'
    '\t\t250000.0000\tvalued at "fair" value\n'
)


def test_quoted_fields_with_tabs_parse_without_shifting(con, tmp_path) -> None:
    num = _tsv(tmp_path / "num.txt", NUM_COLUMNS, [_num_row()])
    with num.open("a") as handle:
        handle.write(QUOTED_ROWS.format(adsh=ADSH))
    sub = _tsv(tmp_path / "sub.txt", SUB_COLUMNS, [_sub_row()])

    rec = convert(con, sub, num, 1, 3)

    assert rec.num.rows_quarantined == 0
    rows = con.execute(
        "SELECT tag, segments, coreg, value, footnote FROM num WHERE tag LIKE 'Investment%'"
        " ORDER BY tag"
    ).fetchall()
    assert rows == [
        (
            "InvestmentOwnedAtCost",
            "InvestmentIdentifier=Lafayette Square Mortgage Solutions, LLC\t | Equity;",
            None,
            Decimal("300000.0000"),
            None,
        ),
        (
            "InvestmentOwnedAtFairValue",
            "InvestmentIdentifier=NC Ocala Co-Invest Beta, LP\t | Aerospace\t & Defense;",
            None,
            Decimal("250000.0000"),
            'valued at "fair" value',
        ),
    ]


def test_malformed_lines_are_quarantined_and_counted(con, tmp_path) -> None:
    sub = _tsv(tmp_path / "sub.txt", SUB_COLUMNS, [_sub_row()])
    num = _tsv(tmp_path / "num.txt", NUM_COLUMNS, [_num_row()])
    with num.open("a") as handle:
        handle.write("a line\twith far\ttoo few columns\n")

    rec = convert(con, sub, num, 1, 2, quarantine_limit=1.0)

    assert rec.num.rows_read == 1
    assert rec.num.rows_quarantined == 1
    saved = write_quarantine(con, tmp_path / "silver", "2026q3")
    assert saved["sub"] is None
    line, raw = con.execute(
        "SELECT line, raw_line FROM read_parquet(?)", [str(saved["num"])]
    ).fetchone()
    assert line == 3
    assert raw.startswith("a line")


def test_too_many_bad_rows_fails(con, tmp_path) -> None:
    rows = [_num_row(), _num_row(tag="Assets", qtrs="0", value="not a number")]

    with pytest.raises(ReconciliationError, match="limit"):
        _convert(con, tmp_path, [_sub_row()], rows)


def test_missing_rows_fail_reconciliation(con, tmp_path) -> None:
    with pytest.raises(ReconciliationError, match="manifest says 5"):
        _convert(con, tmp_path, [_sub_row()], [_num_row()], expected_num=5)


def test_rows_without_a_filing_are_counted(con, tmp_path) -> None:
    rows = [_num_row(), _num_row(adsh="0000000000-26-999999")]

    rec = _convert(con, tmp_path, [_sub_row()], rows)

    assert rec.num_rows_without_filing == 1


def test_parquet_partitions_read_back(con, tmp_path) -> None:
    _convert(con, tmp_path, [_sub_row()], [_num_row(), _num_row(tag="Assets", qtrs="0")])

    written = write_parquet(con, tmp_path / "silver", "2026q3")

    pattern = str(tmp_path / "silver" / "fsds" / "num" / "*" / "*.parquet")
    rows = con.execute(
        "SELECT source_quarter, count(*) FROM read_parquet(?, hive_partitioning = true) GROUP BY 1",
        [pattern],
    ).fetchall()
    assert rows == [("2026q3", 2)]
    assert written["num"].name == "part-0.parquet"
