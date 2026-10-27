"""Unit tests for Financial Statement Data Set paths."""

from __future__ import annotations

import pytest

from earningswatch import fsds


@pytest.mark.parametrize("raw", ["2026q3", "2026Q3", " 2026q3 "])
def test_quarter_is_normalised(raw: str) -> None:
    assert fsds.validate_quarter(raw) == "2026q3"


@pytest.mark.parametrize("bad", ["2026q5", "2026-q3", "26q3", "2008q4", "q3"])
def test_bad_quarters_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="Not a valid FSDS quarter"):
        fsds.validate_quarter(bad)


def test_zip_url() -> None:
    assert fsds.zip_url("2026q3") == (
        "https://www.sec.gov/files/dera/data/financial-statement-data-sets/2026q3.zip"
    )


def test_zip_url_with_moved_base() -> None:
    assert fsds.zip_url("2026q3", "https://example.com/fsds/") == (
        "https://example.com/fsds/2026q3.zip"
    )


def test_bronze_keys() -> None:
    assert fsds.zip_key("2026q3") == "bronze/source=fsds/quarter=2026q3/2026q3.zip"
    assert fsds.member_key("2026q3", "num.txt") == "bronze/source=fsds/quarter=2026q3/num.txt"
