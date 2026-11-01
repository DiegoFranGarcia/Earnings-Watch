"""Unit tests for the SEC ticker file: snapshot dates, keys and the strict parser."""

from __future__ import annotations

import datetime as dt

import pytest

from earningswatch import company_tickers as ct

# The file's real layout: column names once, then one list of values per listing.
DOCUMENT = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [1067983, "BERKSHIRE HATHAWAY INC", "BRK-B", "NYSE"],
        [1234567, "Example Holdings Corp", "EXHC", None],
    ],
}


def _utc(*args: int) -> dt.datetime:
    return dt.datetime(*args, tzinfo=dt.UTC)


def test_snapshot_date_is_the_logical_date_in_utc() -> None:
    assert ct.snapshot_date(_utc(2026, 10, 30, 7)) == dt.date(2026, 10, 30)


def test_todays_run_is_current_even_if_it_starts_late() -> None:
    # The 07:00 run starting at 15:00 after the laptop woke up: still today's file.
    assert ct.is_current(_utc(2026, 10, 30, 7), now=_utc(2026, 10, 30, 15)) is True


def test_a_backfill_run_for_a_past_day_is_not_current() -> None:
    # Saving today's tickers under 1 March would invent history nobody observed.
    assert ct.is_current(_utc(2026, 3, 1, 7), now=_utc(2026, 10, 30, 15)) is False


def test_keys() -> None:
    day = dt.date(2026, 10, 30)
    assert ct.bronze_key(day) == (
        "bronze/source=company_tickers/date=2026-10-30/company_tickers_exchange.json"
    )
    assert ct.silver_key(day) == "silver/company_tickers/date=2026-10-30/part-0.parquet"


def test_parses_the_real_layout() -> None:
    listings = ct.parse_tickers(DOCUMENT)

    assert len(listings) == 3
    assert listings[0] == ct.TickerListing(320193, "Apple Inc.", "AAPL", "Nasdaq")
    assert listings[1].ticker == "BRK-B"  # share classes keep their punctuation
    assert listings[2].exchange is None


def test_rejects_changed_columns() -> None:
    changed = {"fields": ["cik", "ticker", "name", "exchange"], "data": []}  # reordered
    with pytest.raises(ct.TickerFileFormatError, match="expected fields"):
        ct.parse_tickers(changed)


def test_rejects_a_short_row() -> None:
    broken = {"fields": DOCUMENT["fields"], "data": [[320193, "Apple Inc.", "AAPL"]]}
    with pytest.raises(ct.TickerFileFormatError, match="3 values"):
        ct.parse_tickers(broken)
