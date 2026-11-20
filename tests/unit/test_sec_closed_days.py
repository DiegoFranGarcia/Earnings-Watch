"""The days EDGAR was closed, which move filing deadlines: checked against published calendars.

OPM's federal holiday lists (2011 to 2020, observed dates) and the SEC's EDGAR calendar for
2026 are copied here as they were published; the generator must agree with them exactly, and
the committed seed must be what the generator writes.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "make_sec_closed_days", ROOT / "scripts" / "make_sec_closed_days.py"
)
closed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(closed)

# https://www.opm.gov/Operating_Status_Schedules/fedhol (observed dates; 2011's New Year's Day
# is observed on 2010-12-31, a Friday, which is checked on its own below).
OPM = {
    2011: "01-17 02-21 05-30 07-04 09-05 10-10 11-11 11-24 12-26",
    2012: "01-02 01-16 02-20 05-28 07-04 09-03 10-08 11-12 11-22 12-25",
    2013: "01-01 01-21 02-18 05-27 07-04 09-02 10-14 11-11 11-28 12-25",
    2014: "01-01 01-20 02-17 05-26 07-04 09-01 10-13 11-11 11-27 12-25",
    2015: "01-01 01-19 02-16 05-25 07-03 09-07 10-12 11-11 11-26 12-25",
    2016: "01-01 01-18 02-15 05-30 07-04 09-05 10-10 11-11 11-24 12-26",
    2017: "01-02 01-16 02-20 05-29 07-04 09-04 10-09 11-10 11-23 12-25",
    2018: "01-01 01-15 02-19 05-28 07-04 09-03 10-08 11-12 11-22 12-25",
    2019: "01-01 01-21 02-18 05-27 07-04 09-02 10-14 11-11 11-28 12-25",
    2020: "01-01 01-20 02-17 05-25 07-03 09-07 10-12 11-11 11-26 12-25",
}
# https://www.sec.gov/submit-filings/filer-support-resources/edgar-calendar
EDGAR_2026 = "01-01 01-19 02-16 05-25 06-19 07-03 09-07 10-12 11-11 11-26 12-25"


def dates(year: int, days: str) -> set[dt.date]:
    return {dt.date.fromisoformat(f"{year}-{d}") for d in days.split()}


def holidays_in(year: int) -> set[dt.date]:
    return {
        d for d, _, source in closed.closed_days() if d.year == year and source == closed.US_CODE
    }


def test_federal_holidays_match_opm_and_the_edgar_calendar() -> None:
    assert dt.date(2010, 12, 31) in holidays_in(2010)
    for year, days in OPM.items():
        assert holidays_in(year) == dates(year, days), year
    assert holidays_in(2026) == dates(2026, EDGAR_2026)


def test_juneteenth_from_2021_and_saturday_holidays_observed_on_friday() -> None:
    assert dt.date(2021, 6, 18) in holidays_in(2021)  # June 19, 2021 was a Saturday
    assert not any(d.month == 6 for d in holidays_in(2020))
    assert dt.date(2021, 12, 31) in holidays_in(2021)  # New Year's Day 2022, a Saturday


def test_closures_are_weekdays_with_a_source_and_every_day_is_listed_once() -> None:
    rows = closed.closed_days()
    assert len({d for d, _, _ in rows}) == len(rows)
    assert all(d.weekday() < 5 for d, _, _ in rows)
    assert {dt.date(2025, 1, 9), dt.date(2025, 12, 26), dt.date(2018, 12, 5)} <= {
        d for d, _, _ in rows
    }
    assert all(source for _, _, source in rows)
    assert rows[0][0].year == closed.FIRST_YEAR and rows[-1][0].year == closed.LAST_YEAR


def test_the_committed_seed_is_what_the_script_writes(tmp_path) -> None:
    out = tmp_path / "sec_closed_days.csv"
    closed.write(out)
    assert closed.SEED.read_text() == out.read_text()


def test_federal_holidays_agree_with_the_daily_index_dags_calendar() -> None:
    """The daily-index DAG skips the same holidays: the two lists must not drift apart."""
    from earningswatch import daily_index

    for year in range(closed.FIRST_YEAR, closed.LAST_YEAR + 1):
        assert holidays_in(year) == daily_index.federal_holidays(year), year
