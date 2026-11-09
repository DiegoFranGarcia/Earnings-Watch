"""Unit tests for the volume checks: grading, baselines, and what they record."""

from __future__ import annotations

import pytest

from earningswatch.volume import (
    CheckResult,
    describe,
    failures,
    grade,
    previous_year,
    run_volume_checks,
)


@pytest.mark.parametrize(
    ("observed", "baseline", "expected"),
    [
        (100, 100.0, "pass"),
        (74, 100.0, "warn"),  # below 75%
        (49, 100.0, "fail"),  # below 50%: half a load
        (151, 100.0, "warn"),  # above 150%
        (201, 100.0, "fail"),  # above 200%: loaded twice
        (5, None, "skip"),  # no history to compare with
    ],
)
def test_grades_follow_the_thresholds(observed, baseline, expected) -> None:
    got = grade(observed, baseline, fail_below=0.5, warn_below=0.75, warn_above=1.5, fail_above=2.0)
    assert got == expected


def test_daily_volumes_have_no_upper_bound() -> None:
    # Deadline days are several times busier than usual; that is not a fault.
    assert grade(400, 100.0, fail_below=0.5, warn_below=0.75) == "pass"


def test_quarters_compare_with_the_same_quarter_a_year_earlier() -> None:
    assert previous_year("2026q3") == "2025q3"
    assert previous_year("2010q1") == "2009q1"
    with pytest.raises(ValueError):
        previous_year("2026q5")


class FakeCursor:
    """Answers the daily query, the latest quarter, then the two quarter counts."""

    def __init__(self, daily, quarter, counts) -> None:
        self.answers = [daily, (quarter,)]
        self.counts = counts
        self.inserted: list[tuple] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        if sql.startswith("INSERT INTO AUDIT.DQ_RESULTS"):
            self.inserted.append(params)

    def fetchone(self):
        return self.answers.pop(0)

    def fetchall(self):
        return list(self.counts.items())


def test_a_half_quarter_fails_and_every_result_is_recorded() -> None:
    cursor = FakeCursor(
        daily=("2026-11-06", 4_100, 4_000.0),
        quarter="2026q3",
        counts={"2026q3": 1_800_000, "2025q3": 3_720_080},  # under half the usual numbers
    )
    results = run_volume_checks(cursor, run_id="scheduled__x")

    assert [r.outcome for r in results] == ["pass", "fail"]
    assert [r.check_name for r in failures(results)] == ["quarterly_facts"]
    assert describe(failures(results)[0]) == "quarterly_facts 2026q3: 1,800,000 (48% of usual)"
    assert len(cursor.inserted) == 2 and cursor.inserted[1][5] == "fail"


def test_just_above_half_is_a_warning_not_a_failure() -> None:
    # 1.9m of 3.72m is 51%: low enough to look at, not low enough to block.
    assert grade(1_900_000, 3_720_080.0, fail_below=0.5, warn_below=0.75) == "warn"


def test_a_ratio_is_only_reported_when_there_is_a_baseline() -> None:
    assert CheckResult("c", "s", 5, None, "skip").ratio is None
    assert describe(CheckResult("c", "s", 5, None, "skip")) == "c s: 5 (no baseline yet)"
