"""Write dbt/seeds/sec_closed_days.csv: the weekdays EDGAR accepted no filings, 1993 to 2027.

A filing deadline that falls on a weekend or one of these days moves to the next business day
(Exchange Act Rule 0-3: "if the last day on which papers can be accepted as timely filed falls
on a Saturday, Sunday or holiday, such papers may be filed on the first business day
following"). int_sec_calendar turns this list into each date's next business day.

Two kinds of day:

- Federal holidays (5 U.S.C. 6103), by rule: a holiday on a Saturday is observed the Friday
  before, one on a Sunday the Monday after. Juneteenth from 2021. Inauguration Day is left out:
  EDGAR stayed open on it (SEC announcements for 2017 and 2021).
- Other days the federal government closed and the SEC treated as holidays for filing purposes
  (executive orders, national days of mourning), from 2009, when the financial data begins,
  each with its source. Earlier closures are not listed: they only matter for deadlines before
  2009, which only filings made years late, from 2009 on, can have.

Run it again, and add any new closure to CLOSURES, when a year is added (the seed has to cover
every deadline: dbt's tests say when it falls short):

    uv run python scripts/make_sec_closed_days.py
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "dbt" / "seeds" / "sec_closed_days.csv"
FIRST_YEAR = 1993  # EDGAR's first year
LAST_YEAR = 2027

US_CODE = "5 U.S.C. 6103"
CLOSURES = {
    dt.date(2012, 12, 24): (
        "Christmas Eve: executive departments closed",
        "Executive Order 13633",
    ),
    dt.date(2014, 12, 26): (
        "Day after Christmas: executive departments closed",
        "Executive Order 13682; EDGAR not operational (SEC, December 2014)",
    ),
    dt.date(2018, 12, 5): (
        "National day of mourning for President George H. W. Bush",
        "https://www.sec.gov/newsroom/whats-new/edgar-be-closed-wednesday-december-5-2018",
    ),
    dt.date(2018, 12, 24): (
        "Christmas Eve: federal government closed",
        "https://www.sec.gov/newsroom/whats-new/december-24-2018-federal-holiday-edgar-filing-purposes",
    ),
    dt.date(2019, 12, 24): (
        "Christmas Eve: federal government closed",
        "https://www.sec.gov/newsroom/whats-new/edgar-will-be-closed-tuesday-december-24-2019-wednesday-december-25-2019",
    ),
    dt.date(2020, 12, 24): (
        "Christmas Eve: federal government closed",
        "https://www.sec.gov/oit/announcement/edgar-holiday-closure-2020",
    ),
    dt.date(2024, 12, 24): (
        "Christmas Eve: federal government closed",
        "https://www.sec.gov/newsroom/whats-new/edgar-closed-24-25-december-2024",
    ),
    dt.date(2025, 1, 9): (
        "National day of mourning for President Jimmy Carter",
        "https://www.sec.gov/newsroom/whats-new/edgar-closed-january-9-2025",
    ),
    dt.date(2025, 12, 24): (
        "Christmas Eve: federal government closed",
        "https://www.sec.gov/newsroom/whats-new/edgar-will-be-closed-december-24-2025-through-december-26-2025",
    ),
    dt.date(2025, 12, 26): (
        "Day after Christmas: federal government closed",
        "https://www.sec.gov/newsroom/whats-new/edgar-will-be-closed-december-24-2025-through-december-26-2025",
    ),
}


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """The nth (1-based; -1 for the last) given weekday (Monday 0) of a month."""
    if n > 0:
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    following = dt.date(year + month // 12, month % 12 + 1, 1)
    last = following - dt.timedelta(days=1)
    return last - dt.timedelta(days=(last.weekday() - weekday) % 7)


def observed(day: dt.date) -> dt.date:
    """The day a holiday is observed: Saturday's on the Friday, Sunday's on the Monday."""
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def federal_holidays(year: int) -> dict[dt.date, str]:
    """The days federal holidays falling in this year are observed (the observed day can be
    in the year before: New Year's Day on a Saturday is observed on December 31)."""
    days = {
        observed(dt.date(year, 1, 1)): "New Year's Day",
        nth_weekday(year, 1, 0, 3): "Birthday of Martin Luther King, Jr.",
        nth_weekday(year, 2, 0, 3): "Washington's Birthday",
        nth_weekday(year, 5, 0, -1): "Memorial Day",
        observed(dt.date(year, 7, 4)): "Independence Day",
        nth_weekday(year, 9, 0, 1): "Labor Day",
        nth_weekday(year, 10, 0, 2): "Columbus Day",
        observed(dt.date(year, 11, 11)): "Veterans Day",
        nth_weekday(year, 11, 3, 4): "Thanksgiving Day",
        observed(dt.date(year, 12, 25)): "Christmas Day",
    }
    if year >= 2021:
        days[observed(dt.date(year, 6, 19))] = "Juneteenth National Independence Day"
    return days


def closed_days(first: int = FIRST_YEAR, last: int = LAST_YEAR) -> list[tuple[dt.date, str, str]]:
    """Every closed weekday from January 1 of the first year to December 31 of the last."""
    days: dict[dt.date, tuple[str, str]] = {}
    for year in range(first, last + 2):
        for day, name in federal_holidays(year).items():
            days[day] = (name, US_CODE)
    days.update(CLOSURES)
    start, end = dt.date(first, 1, 1), dt.date(last, 12, 31)
    return [(day, *days[day]) for day in sorted(days) if start <= day <= end]


def write(path: Path = SEED) -> int:
    rows = closed_days()
    with path.open("w", newline="") as f:
        out = csv.writer(f, lineterminator="\n")
        out.writerow(["closed_date", "reason", "source"])
        out.writerows((day.isoformat(), reason, source) for day, reason, source in rows)
    return len(rows)


if __name__ == "__main__":
    print(f"{write()} days written to {SEED.relative_to(ROOT)}")
