"""The SEC's ticker file: today's CIK, name, ticker and exchange for each listing.

The SEC keeps no history of this file, so EarningsWatch saves a dated copy every day.
Those snapshots become the only record of ticker changes over time. A snapshot can
only ever be taken of today's file, never of a past day.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
EXPECTED_FIELDS = ["cik", "name", "ticker", "exchange"]
# A run may start a little late (a laptop waking up, a busy scheduler), but a run whose
# logical date is more than this old would be saving today's file under a past date.
SNAPSHOT_TOLERANCE = dt.timedelta(days=1)


class TickerFileFormatError(ValueError):
    """The file does not have the layout this parser was written for."""


@dataclass(frozen=True)
class TickerListing:
    cik: int
    name: str
    ticker: str
    exchange: str | None  # some listings carry no exchange


def snapshot_date(logical: dt.datetime) -> dt.date:
    """The date a snapshot is filed under: its logical date, in UTC."""
    return logical.astimezone(dt.UTC).date()


def is_current(logical: dt.datetime, now: dt.datetime) -> bool:
    """True when a run is close enough to now that today's file belongs to its date.

    A backfill run for a past date must not snapshot: the SEC serves only today's file,
    and filing it under a past date would invent history that was never observed.
    """
    return now - logical <= SNAPSHOT_TOLERANCE


def bronze_key(day: dt.date) -> str:
    return f"bronze/source=company_tickers/date={day:%Y-%m-%d}/company_tickers_exchange.json"


def silver_key(day: dt.date) -> str:
    return f"silver/company_tickers/date={day:%Y-%m-%d}/part-0.parquet"


def parse_tickers(document: dict) -> list[TickerListing]:
    """Read the file's {"fields": [...], "data": [[...], ...]} layout, strictly."""
    fields = document.get("fields")
    if fields != EXPECTED_FIELDS:
        raise TickerFileFormatError(f"expected fields {EXPECTED_FIELDS}, got {fields}")
    listings = []
    for number, row in enumerate(document.get("data", []), start=1):
        if len(row) != len(EXPECTED_FIELDS):
            raise TickerFileFormatError(f"row {number} has {len(row)} values: {row!r}")
        cik, name, ticker, exchange = row
        listings.append(TickerListing(int(cik), str(name), str(ticker), exchange or None))
    return listings
