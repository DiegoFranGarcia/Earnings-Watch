"""Unit tests for the daily index: run dates, the holiday calendar, paths and the parser."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from earningswatch import daily_index as di

# The first lines of the real master.20261023.idx landed in bronze. Note the line holding a
# single space before the column names: it is in the SEC's file, so it is in the fixture.
REAL_FILE_HEAD = (
    "\n".join(
        [
            "Description:           Daily Index of EDGAR Dissemination Feed",
            "Last Data Received:    Oct 23, 2026",
            "Comments:              webmaster@sec.gov",
            "Anonymous FTP:         ftp://ftp.sec.gov/edgar/",
            " ",
            "CIK|Company Name|Form Type|Date Filed|File Name",
            "-" * 80,
            "1000275|ROYAL BANK OF CANADA|424B2|20261023|edgar/data/1000275/0000950103-26-016040.txt",  # noqa: E501 - real SEC rows, kept intact
            "1000275|ROYAL BANK OF CANADA|424B2|20261023|edgar/data/1000275/0000950103-26-016041.txt",  # noqa: E501 - real SEC rows, kept intact
            "2488|ADVANCED MICRO DEVICES INC|8-K|20261023|edgar/data/2488/0000002488-26-000150.txt",
        ]
    )
    + "\n"
)


def _utc(*args: int) -> dt.datetime:
    return dt.datetime(*args, tzinfo=dt.UTC)


# -- which day ------------------------------------------------------------------


def test_a_run_fetches_the_day_before_its_logical_date() -> None:
    # Airflow 3: Wednesday 28 Oct's 06:00 run has logical date Wednesday 06:00.
    assert di.target_date(_utc(2026, 10, 28, 6)) == dt.date(2026, 10, 27)


def test_target_date_uses_utc() -> None:
    eastern = dt.timezone(dt.timedelta(hours=-4))
    # 23:00 on the 27th in New York is already 03:00 on the 28th in UTC.
    assert di.target_date(dt.datetime(2026, 10, 27, 23, tzinfo=eastern)) == dt.date(2026, 10, 27)


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (
            2025,
            {
                "2025-01-01", "2025-01-20", "2025-02-17", "2025-05-26", "2025-06-19",
                "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27",
                "2025-12-25",
            },
        ),
        (
            2026,
            {
                "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19",
                "2026-07-03",  # 4 July 2026 is a Saturday: observed Friday 3 July
                "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25",
            },
        ),
    ],
)  # fmt: skip
def test_federal_holidays(year: int, expected: set[str]) -> None:
    assert {d.isoformat() for d in di.federal_holidays(year)} == expected


def test_new_year_on_a_saturday_is_observed_the_friday_before() -> None:
    # 1 January 2022 was a Saturday, so 31 December 2021 was the holiday.
    assert dt.date(2021, 12, 31) in di.federal_holidays(2021)
    assert dt.date(2022, 1, 1) not in di.federal_holidays(2022)


def test_sunday_holiday_is_observed_monday() -> None:
    assert dt.date(2022, 12, 26) in di.federal_holidays(2022)  # Christmas 2022 was a Sunday


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (dt.date(2026, 10, 23), True),  # a Friday
        (dt.date(2026, 10, 24), False),  # Saturday
        (dt.date(2026, 10, 25), False),  # Sunday
        (dt.date(2026, 11, 26), False),  # Thanksgiving
        (dt.date(2026, 11, 27), True),  # the day after Thanksgiving: EDGAR is open
    ],
)
def test_is_business_day(day: dt.date, expected: bool) -> None:
    assert di.is_business_day(day) is expected


# -- where the file lives ---------------------------------------------------------


def test_urls_and_keys() -> None:
    day = dt.date(2026, 10, 23)
    assert di.file_url(day) == (
        "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/master.20261023.idx"
    )
    assert di.quarter_folder_url(dt.date(2026, 3, 31)).endswith("/2026/QTR1/")
    assert di.bronze_key(day) == "bronze/source=daily_index/date=2026-10-23/master.20261023.idx"
    assert di.silver_key(day) == "silver/daily_index/date=2026-10-23/part-0.parquet"


def test_published_files_reads_an_edgar_listing() -> None:
    listing = {"directory": {"item": [{"name": "master.20261023.idx"}, {"name": "index.json"}]}}
    assert di.published_files(listing) == {"master.20261023.idx", "index.json"}
    assert di.published_files({}) == set()


def test_a_missing_index_is_only_final_after_the_grace_period() -> None:
    day = dt.date(2026, 10, 23)
    assert di.missing_is_final(day, _utc(2026, 10, 24, 6)) is False  # it may still come
    assert di.missing_is_final(day, _utc(2026, 10, 27, 0)) is True  # it never will


# -- has every recent business day landed? ----------------------------------------------

SEED = Path(__file__).resolve().parents[2] / "dbt" / "seeds" / "sec_closed_days.csv"


def _receipts(days) -> set[str]:
    return {di.receipt_key(day) for day in days} | {di.bronze_key(day) for day in days}


def test_the_receipt_is_the_manifest_bronze_writes() -> None:
    from earningswatch import bronze

    day = dt.date(2026, 11, 5)
    assert di.receipt_key(day) == bronze.manifest_key(di.bronze_key(day))


def test_the_check_covers_four_weeks_of_business_days_past_the_grace() -> None:
    days = di.days_to_check(_utc(2026, 11, 21, 6, 30))
    # From 2026-10-24 (a Saturday, so the 26th), to 2026-11-17: the 18th to the 20th may
    # still be published. Weekends and Veterans Day (11-11) are not business days.
    assert days[0] == dt.date(2026, 10, 26)
    assert days[-1] == dt.date(2026, 11, 17)
    assert dt.date(2026, 11, 11) not in days
    assert all(day.weekday() < 5 for day in days)
    assert len(days) == 16
    assert dt.date(2026, 11, 5) in days  # the day lost on 2026-11-06 would have been reported


def test_the_check_starts_no_earlier_than_the_history() -> None:
    days = di.days_to_check(_utc(2025, 1, 10, 6))
    assert days == [dt.date(2025, 1, 2), dt.date(2025, 1, 3), dt.date(2025, 1, 6)]
    assert di.days_to_check(_utc(2025, 1, 2, 6)) == []


def test_a_day_without_its_receipt_is_missing() -> None:
    days = di.days_to_check(_utc(2026, 11, 21, 6, 30))
    landed = [day for day in days if day != dt.date(2026, 11, 5)]
    assert di.missing_days(days, _receipts(landed), closed=set()) == [dt.date(2026, 11, 5)]
    assert di.missing_days(days, _receipts(days), closed=set()) == []


def test_a_file_without_its_receipt_has_not_landed() -> None:
    # The receipt is written last: a file alone is an unfinished landing.
    day = dt.date(2026, 11, 5)
    assert di.missing_days([day], {di.bronze_key(day)}, closed=set()) == [day]


def test_a_day_edgar_was_closed_is_not_missing() -> None:
    day = dt.date(2025, 12, 24)
    assert di.missing_days([day], set(), closed={day}) == []


def test_the_seed_lists_the_closures_and_not_the_lost_day() -> None:
    closed = di.read_closed_days(SEED)
    assert {dt.date(2025, 1, 9), dt.date(2025, 12, 24), dt.date(2025, 12, 26)} <= closed
    assert dt.date(2026, 11, 5) not in closed


@pytest.mark.parametrize(
    "content", ["", "closed_date,reason,source\n", "day,reason\n2025-12-24,Christmas Eve\n"]
)
def test_a_seed_that_cannot_be_read_fails_loudly(tmp_path, content: str) -> None:
    seed = tmp_path / "sec_closed_days.csv"
    seed.write_text(content)
    with pytest.raises(ValueError, match="closed_date"):
        di.read_closed_days(seed)


def test_a_missing_seed_fails_loudly(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        di.read_closed_days(tmp_path / "sec_closed_days.csv")


def test_the_alert_names_the_days_on_one_short_line() -> None:
    one = di.describe_missing([dt.date(2026, 11, 5)])
    assert one.startswith("1 business day has no daily index in bronze: 2026-11-05 (Thu).")
    many = di.describe_missing([dt.date(2026, 10, d) for d in (19, 20, 21, 22, 23, 26, 27)])
    assert many.startswith("7 business days have no daily index in bronze: 2026-10-19 (Mon),")
    assert "2026-10-23 (Fri) and 2 more." in many
    for text in (one, many):
        assert "\n" not in text
        assert len(text) <= 300  # the alert shows the error's first line, up to 300 characters


# -- reading the file ---------------------------------------------------------------


def test_parses_the_real_layout() -> None:
    filings = di.parse_master_index(REAL_FILE_HEAD.splitlines(keepends=True))

    assert len(filings) == 3
    amd = filings[2]
    assert amd.cik == 2488
    assert amd.company_name == "ADVANCED MICRO DEVICES INC"
    assert amd.form_type == "8-K"
    assert amd.date_filed == dt.date(2026, 10, 23)
    assert amd.accession_number == "0000002488-26-000150"


def test_rejects_a_file_without_the_header() -> None:
    with pytest.raises(di.DailyIndexFormatError, match="header"):
        di.parse_master_index(["just some text\n"])


def test_rejects_a_row_with_the_wrong_number_of_fields() -> None:
    bad = REAL_FILE_HEAD + "123|ONLY|THREE FIELDS\n"
    with pytest.raises(di.DailyIndexFormatError, match="3 fields"):
        di.parse_master_index(bad.splitlines(keepends=True))
