"""EDGAR's daily index: which day a run fetches, where the file lives, and how to read it.

The daily index lists every filing EDGAR accepted on one business day. It is built
nightly from about 10 p.m. Eastern, so a run fetches the index for the day *before*
its logical date.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DAILY_INDEX_BASE_URL = "https://www.sec.gov/Archives/edgar/daily-index"
HEADER = "CIK|Company Name|Form Type|Date Filed|File Name"
# How long after a business day EDGAR must have published its index. Past this, a missing
# file means EDGAR published none (an unscheduled closure); before it, it may still be coming.
PUBLISH_GRACE = dt.timedelta(days=3)
# The daily index history starts here (sec_daily_index's start_date).
FIRST_DAY = dt.date(2025, 1, 1)
# How far back each morning's check looks for a business day with no index in bronze. A gap is
# reported every morning while it is inside this window; older ones only by
# scripts/reconcile_bronze.py.
CHECK_WINDOW = dt.timedelta(days=28)


class DailyIndexFormatError(ValueError):
    """The file does not have the layout this parser was written for."""


# -- which day ----------------------------------------------------------------


def target_date(logical: dt.datetime) -> dt.date:
    """The day whose index a run fetches: the calendar day before its logical date.

    Airflow 3 schedules cron DAGs with CronTriggerTimetable, so a 06:00 run on Wednesday
    has a logical date (and data interval) of Wednesday 06:00, not Tuesday. Wednesday's
    index does not exist until that night, so the run fetches Tuesday's.
    """
    return logical.astimezone(dt.UTC).date() - dt.timedelta(days=1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The n-th given weekday of a month (Monday is 0); n = -1 means the last one."""
    if n > 0:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    next_month = dt.date(year + month // 12, month % 12 + 1, 1)
    last = next_month - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: dt.date) -> dt.date:
    """Federal rule: a holiday on Saturday is observed Friday, on Sunday the next Monday."""
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def _holidays_dated(year: int) -> set[dt.date]:
    fixed = [dt.date(year, 1, 1), dt.date(year, 7, 4), dt.date(year, 11, 11), dt.date(year, 12, 25)]
    if year >= 2021:
        fixed.append(dt.date(year, 6, 19))  # Juneteenth became a federal holiday in 2021
    floating = [
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day: third Monday of January
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday: third Monday of February
        _nth_weekday(year, 5, 0, -1),  # Memorial Day: last Monday of May
        _nth_weekday(year, 9, 0, 1),  # Labor Day: first Monday of September
        _nth_weekday(year, 10, 0, 2),  # Columbus Day: second Monday of October
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving: fourth Thursday of November
    ]
    return {_observed(day) for day in fixed} | set(floating)


def federal_holidays(year: int) -> set[dt.date]:
    """US federal holidays observed in `year`, when EDGAR is closed.

    New Year's Day falling on a Saturday is observed on 31 December of the year before,
    so next year's holidays are computed too and kept if they land in this year.
    """
    candidates = _holidays_dated(year) | _holidays_dated(year + 1)
    return {day for day in candidates if day.year == year}


def is_business_day(day: dt.date) -> bool:
    return day.weekday() < 5 and day not in federal_holidays(day.year)


# -- where the file lives -------------------------------------------------------


def file_name(day: dt.date) -> str:
    return f"master.{day:%Y%m%d}.idx"


def quarter_folder_url(day: dt.date, base_url: str = DAILY_INDEX_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/{day.year}/QTR{(day.month - 1) // 3 + 1}/"


def file_url(day: dt.date, base_url: str = DAILY_INDEX_BASE_URL) -> str:
    return quarter_folder_url(day, base_url) + file_name(day)


def bronze_key(day: dt.date) -> str:
    return f"bronze/source=daily_index/date={day:%Y-%m-%d}/{file_name(day)}"


def receipt_key(day: dt.date) -> str:
    """The day's manifest in bronze, written last when a file lands (bronze.manifest_key)."""
    return bronze_key(day) + ".manifest.json"


def silver_key(day: dt.date) -> str:
    return f"silver/daily_index/date={day:%Y-%m-%d}/part-0.parquet"


def published_files(listing: dict) -> set[str]:
    """File names in an EDGAR folder's index.json listing."""
    return {item["name"] for item in listing.get("directory", {}).get("item", [])}


def missing_is_final(day: dt.date, now: dt.datetime) -> bool:
    """True once a business day is old enough that a missing index will never appear."""
    end_of_day = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), tzinfo=dt.UTC)
    return now >= end_of_day + PUBLISH_GRACE


# -- has every recent business day landed? ---------------------------------------


def read_closed_days(path: Path) -> set[dt.date]:
    """The weekdays EDGAR accepted no filings, from the dbt seed sec_closed_days.csv.

    The same list the timeliness models use. A missing, empty or malformed file raises, so the
    check fails loudly instead of reporting every closure as a gap (or none at all).
    """
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "closed_date" not in rows[0]:
        raise ValueError(f"{path}: expected a closed_date column and at least one row")
    return {dt.date.fromisoformat(row["closed_date"]) for row in rows}


def days_to_check(now: dt.datetime, window: dt.timedelta = CHECK_WINDOW) -> list[dt.date]:
    """The business days in the window whose index must exist by now (past PUBLISH_GRACE)."""
    day = max(FIRST_DAY, (now - window).date())
    days = []
    while missing_is_final(day, now):
        if is_business_day(day):
            days.append(day)
        day += dt.timedelta(days=1)
    return days


def missing_days(days: Iterable[dt.date], keys: set[str], closed: set[dt.date]) -> list[dt.date]:
    """The days with no receipt among bronze's keys, other than days EDGAR was closed."""
    return [day for day in days if receipt_key(day) not in keys and day not in closed]


def describe_missing(missing: list[dt.date], shown: int = 5) -> str:
    """One line for the alert (it shows the first 300 characters of the error)."""
    listed = ", ".join(f"{day:%Y-%m-%d (%a)}" for day in missing[:shown])
    if len(missing) > shown:
        listed += f" and {len(missing) - shown} more"
    count = f"{len(missing)} business day{'s have' if len(missing) > 1 else ' has'}"
    return (
        f"{count} no daily index in bronze: {listed}. If EDGAR published it, land it (runbook: "
        "a day of the daily index is missing); if EDGAR was closed, add it to sec_closed_days.csv."
    )


# -- reading the file -----------------------------------------------------------


@dataclass(frozen=True)
class Filing:
    cik: int
    company_name: str
    form_type: str
    date_filed: dt.date
    filename: str
    accession_number: str


def parse_master_index(lines: Iterable[str]) -> list[Filing]:
    """Parse a master.YYYYMMDD.idx file: free-text header, column names, dashes, then rows."""
    rows = iter(lines)
    for line in rows:
        if line.rstrip("\r\n") == HEADER:
            break
    else:
        raise DailyIndexFormatError(f"header line {HEADER!r} not found")
    separator = next(rows, "").strip()
    if not separator or set(separator) != {"-"}:
        raise DailyIndexFormatError("expected a line of dashes after the header")

    filings = []
    for number, line in enumerate(rows, start=1):
        text = line.rstrip("\r\n")
        if not text.strip():
            continue
        fields = text.split("|")
        if len(fields) != 5:
            raise DailyIndexFormatError(f"data row {number} has {len(fields)} fields: {text!r}")
        cik, company, form, filed, path = fields
        filings.append(
            Filing(
                cik=int(cik),
                company_name=company,
                form_type=form,
                date_filed=dt.datetime.strptime(filed, "%Y%m%d").date(),  # noqa: DTZ007 - a date, no time
                filename=path,
                accession_number=Path(path).stem,
            )
        )
    return filings
