"""Unit tests for which quarter a run handles, and where republished copies go."""

from __future__ import annotations

import datetime as dt

import pytest

from earningswatch import fsds


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (dt.date(2027, 1, 1), "2026q4"),  # January's run collects the quarter just ended
        (dt.date(2026, 4, 1), "2026q1"),
        (dt.date(2026, 7, 1), "2026q2"),
        (dt.date(2026, 10, 1), "2026q3"),
        (dt.date(2009, 7, 1), "2009q2"),  # the first quarter with data
    ],
)
def test_previous_quarter(day: dt.date, expected: str) -> None:
    assert fsds.previous_quarter(day) == expected


def test_version_zip_key_sits_beside_the_original() -> None:
    assert fsds.version_zip_key("2026q3", "20261115") == (
        "bronze/source=fsds/quarter=2026q3/version=20261115/2026q3.zip"
    )
