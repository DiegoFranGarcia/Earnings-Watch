"""Unit tests for quarter lists and ranges."""

from __future__ import annotations

import pytest

from lib.quarters import expand


def test_a_range_crosses_years() -> None:
    assert expand("2009q2..2010q1") == ["2009q2", "2009q3", "2009q4", "2010q1"]


def test_the_full_history_is_seventy_quarters() -> None:
    quarters = expand("2009q2..2026q3")
    assert (len(quarters), quarters[0], quarters[-1]) == (70, "2009q2", "2026q3")


def test_lists_and_ranges_mix_without_repeats() -> None:
    assert expand("2026q3, 2026q1..2026q3,2026Q1") == ["2026q3", "2026q1", "2026q2"]


@pytest.mark.parametrize("bad", ["2026q5", "26q1", "2026-q1", "2026q3..2026q1"])
def test_bad_labels_and_backwards_ranges_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        expand(bad)
