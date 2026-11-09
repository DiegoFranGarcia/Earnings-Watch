"""Unit tests for the pure Spark transforms, on tiny DataFrames."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

import pytest
from fsds_fixtures import ADSH, awkward_quarter, num_row, sub_row, write_quarter

from lib.schemas import NUM_CASTS, NUM_COLUMNS, SUB_CASTS, SUB_COLUMNS
from lib.transforms import (
    count_cast_failures,
    good_rows,
    quarantined_rows,
    read_raw,
    silver_num,
    typed,
)


def _frames(spark, tmp_path, subs, nums, extra=()):
    folder = write_quarter(tmp_path / "quarter=2026q3", subs, nums, extra)
    raw_sub = read_raw(spark, str(folder / "sub.txt"), SUB_COLUMNS)
    raw_num = read_raw(spark, str(folder / "num.txt"), NUM_COLUMNS)
    return raw_sub, raw_num


def _text_frame(spark, rows: list[dict]):
    """num rows as an all-text DataFrame, with the schema given, never inferred."""
    schema = ", ".join(f"{column} string" for column in NUM_COLUMNS)
    return spark.createDataFrame([tuple(r.get(c) for c in NUM_COLUMNS) for r in rows], schema)


def test_columns_get_real_types(spark, tmp_path) -> None:
    raw_sub, raw_num = _frames(spark, tmp_path, [sub_row()], [num_row()])

    sub = typed(good_rows(raw_sub), SUB_COLUMNS, SUB_CASTS).first()
    num = typed(good_rows(raw_num), NUM_COLUMNS, NUM_CASTS).first()

    assert (sub.cik, sub.sic, sub.period, sub.prevrpt, sub.detail) == (
        2488, 3674, dt.date(2026, 6, 30), False, True
    )  # fmt: skip
    assert sub.accepted == dt.datetime(2026, 8, 4, 17, 40)  # noqa: DTZ001 - no zone, on purpose
    assert (sub.fye, sub.zipba, sub.ein) == ("1231", "02134", "941692300"), "codes stay text"
    assert (num.ddate, num.qtrs, num.value) == (dt.date(2026, 6, 30), 2, Decimal("1234000000.0000"))


def test_quoted_tab_stays_inside_its_field(spark, tmp_path) -> None:
    _, raw_num = _frames(spark, tmp_path, [sub_row()], [num_row(segments='"Fund=Alpha\tBeta;"')])

    row = good_rows(raw_num).first()

    assert row.segments == "Fund=Alpha\tBeta;"
    assert row.value == "1234000000.0000", "the columns after it are not shifted"


def test_lines_with_the_wrong_field_count_are_quarantined(spark, tmp_path) -> None:
    too_many = "\t".join("abcdefghijk")  # 11 fields where num has 10
    _, raw_num = _frames(spark, tmp_path, [sub_row()], [num_row()], extra=["too\tfew", too_many])

    assert good_rows(raw_num).count() == 1
    assert sorted(r.raw_line for r in quarantined_rows(raw_num).collect()) == sorted(
        [too_many, "too\tfew"]
    )


def test_cast_failures_are_counted_not_fatal(spark, tmp_path) -> None:
    # Read through the real CSV reader: it turns an empty field into null, as in production.
    rows = [
        num_row(value="abc"),
        num_row(tag="Assets", ddate="2026063"),
        num_row(tag="X", value=""),
    ]
    _, raw_num = _frames(spark, tmp_path, [sub_row()], rows)

    assert count_cast_failures(good_rows(raw_num), NUM_CASTS) == 2, "empty is missing, not bad"


def test_silver_num_dedupes_flags_and_enriches(spark, tmp_path) -> None:
    raw_sub, _ = _frames(spark, tmp_path, [sub_row()], [])
    sub = typed(good_rows(raw_sub), SUB_COLUMNS, SUB_CASTS)
    rows = [
        num_row(),
        num_row(),  # exact duplicate
        num_row(tag="Rev", value="1"),  # same key as the next row, different value
        num_row(tag="Rev", value="2"),
        num_row(tag="Assets", qtrs="0", segments="Seg=A;"),
    ]
    num = typed(_text_frame(spark, rows), NUM_COLUMNS, NUM_CASTS)

    out = {(r.tag, str(r.value)): r for r in silver_num(num, sub).collect()}

    assert len(out) == 4, "the exact duplicate is gone"
    income = out[("NetIncomeLoss", "1234000000.0000")]
    assert income.adsh == ADSH
    assert (income.cik, income.form, income.fp) == (2488, "10-Q", "Q2")
    assert income.filed == dt.date(2026, 8, 5)
    assert (income.is_entity_total, income.period_type, income.has_key_conflict) == (
        True, "duration", False
    )  # fmt: skip
    assert out[("Rev", "1.0000")].has_key_conflict
    assert out[("Rev", "2.0000")].has_key_conflict
    assets = out[("Assets", "1234000000.0000")]
    assert (assets.is_entity_total, assets.period_type) == (False, "instant")


def test_awkward_quarter_reads_cleanly(spark, tmp_path) -> None:
    folder = awkward_quarter(tmp_path)
    raw_num = read_raw(spark, str(folder / "num.txt"), NUM_COLUMNS)

    assert good_rows(raw_num).count() == 11
    assert quarantined_rows(raw_num).count() == 1


@pytest.mark.parametrize(
    ("header", "change"),
    [
        ("a\tb\tc", None),  # exactly as expected
        ("a\tnew\tb\tc", "added ['new']"),  # a column inserted mid-file
        ("a\tc\tb", "same columns in a different order"),  # silently wrong without the check
        ("a\tb", "missing ['c']"),
    ],
)
def test_the_header_must_match_the_expected_columns(spark, tmp_path, header, change) -> None:
    from lib.transforms import HeaderMismatch, check_header

    path = tmp_path / "num.txt"
    path.write_text(header + "\n1\t2\t3\n")

    if change is None:
        check_header(spark, str(path), ("a", "b", "c"))
    else:
        with pytest.raises(HeaderMismatch, match=re.escape(change)):
            check_header(spark, str(path), ("a", "b", "c"))
