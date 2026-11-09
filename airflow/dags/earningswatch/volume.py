"""Volume checks: is a load plausible, not just internally consistent?

Count checks prove that RAW holds what silver held. They cannot notice that the SEC published half
a quarter, or a day with a tenth of the usual filings: those load perfectly. These checks compare
the newest data with its own history and grade it pass, warn, fail or skip (no baseline yet).
dbt_build runs them first, as a circuit breaker: a failure stops the build, so the marts keep
their last good data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from earningswatch.snowflake_load import check_quarter

log = logging.getLogger(__name__)

DQ_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS AUDIT.DQ_RESULTS ("
    "check_name VARCHAR, subject VARCHAR, observed NUMBER, baseline NUMBER, ratio FLOAT, "
    "outcome VARCHAR, run_id VARCHAR, checked_at TIMESTAMP_NTZ)"
)


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    subject: str  # what was checked: a day or a quarter
    observed: int
    baseline: float | None
    outcome: str  # pass | warn | fail | skip

    @property
    def ratio(self) -> float | None:
        return self.observed / self.baseline if self.baseline else None


def grade(
    observed: int,
    baseline: float | None,
    fail_below: float,
    warn_below: float,
    warn_above: float | None = None,
    fail_above: float | None = None,
) -> str:
    """Grade observed against baseline by ratio thresholds."""
    if not baseline:
        return "skip"
    ratio = observed / baseline
    if ratio < fail_below or (fail_above is not None and ratio > fail_above):
        return "fail"
    if ratio < warn_below or (warn_above is not None and ratio > warn_above):
        return "warn"
    return "pass"


def previous_year(quarter: str) -> str:
    """'2026q3' -> '2025q3': the same quarter a year earlier, for a like-for-like comparison."""
    check_quarter(quarter)
    return f"{int(quarter[:4]) - 1}{quarter[4:]}"


DAILY_SQL = """
with days as (
    select _source_date as day, count(distinct accession_number) as filings
    from RAW.DAILY_INDEX
    group by 1
),
latest as (select max(day) as day from days),
previous as (
    select filings from days where day < (select day from latest)
    order by day desc limit 20
)
select
    (select day from latest),
    (select filings from days where day = (select day from latest)),
    (select median(filings) from previous)
"""


def check_daily_filings(cursor) -> CheckResult:
    cursor.execute(DAILY_SQL)
    day, filings, baseline = cursor.fetchone()
    if day is None:
        return CheckResult("daily_filings", "none loaded", 0, None, "skip")
    baseline = float(baseline) if baseline is not None else None
    outcome = grade(int(filings), baseline, fail_below=0.5, warn_below=0.75)
    return CheckResult("daily_filings", str(day), int(filings), baseline, outcome)


def check_quarterly_facts(cursor) -> CheckResult:
    cursor.execute("SELECT MAX(_source_quarter) FROM RAW.FSDS_SUB")
    (quarter,) = cursor.fetchone()
    if quarter is None:
        return CheckResult("quarterly_facts", "none loaded", 0, None, "skip")
    year_before = previous_year(quarter)
    cursor.execute(
        "SELECT _source_quarter, COUNT(*) FROM RAW.FSDS_NUM "
        "WHERE _source_quarter IN (%s, %s) GROUP BY 1",
        (quarter, year_before),
    )
    counts = {q: int(n) for q, n in cursor.fetchall()}
    baseline = float(counts[year_before]) if year_before in counts else None
    outcome = grade(
        counts.get(quarter, 0), baseline,
        fail_below=0.5, warn_below=0.75, warn_above=1.5, fail_above=2.0,
    )  # fmt: skip
    return CheckResult("quarterly_facts", quarter, counts.get(quarter, 0), baseline, outcome)


def run_volume_checks(cursor, run_id: str) -> list[CheckResult]:
    """Run every check, record every result in AUDIT.DQ_RESULTS, and return them."""
    results = [check_daily_filings(cursor), check_quarterly_facts(cursor)]
    cursor.execute(DQ_TABLE_SQL)
    for r in results:
        cursor.execute(
            "INSERT INTO AUDIT.DQ_RESULTS VALUES (%s, %s, %s, %s, %s, %s, %s, SYSDATE())",
            (r.check_name, r.subject, r.observed, r.baseline, r.ratio, r.outcome, run_id),
        )
        log.info(
            "%s %s: %s against %s -> %s", r.check_name, r.subject, r.observed, r.baseline, r.outcome
        )
    return results


def failures(results: list[CheckResult]) -> list[CheckResult]:
    return [r for r in results if r.outcome == "fail"]


def describe(result: CheckResult) -> str:
    usual = f"{result.ratio:.0%} of usual" if result.ratio is not None else "no baseline yet"
    return f"{result.check_name} {result.subject}: {result.observed:,} ({usual})"
