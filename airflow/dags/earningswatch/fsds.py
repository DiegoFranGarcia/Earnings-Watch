"""Financial Statement Data Sets (FSDS): where each quarter lives, at the SEC and in bronze."""

from __future__ import annotations

import re

FSDS_BASE_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets"
FSDS_MEMBERS = ("sub.txt", "num.txt", "tag.txt", "pre.txt")
FIRST_YEAR = 2009  # the data sets start in 2009 (2009q1 holds headers only)

_QUARTER = re.compile(r"^(\d{4})q([1-4])$")


def validate_quarter(quarter: str) -> str:
    """Normalise and check a quarter label such as '2026q3'."""
    normalised = quarter.strip().lower()
    match = _QUARTER.match(normalised)
    if match is None or int(match.group(1)) < FIRST_YEAR:
        raise ValueError(f"Not a valid FSDS quarter: {quarter!r} (expected e.g. '2026q3')")
    return normalised


def zip_url(quarter: str, base_url: str = FSDS_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/{validate_quarter(quarter)}.zip"


def bronze_prefix(quarter: str) -> str:
    return f"bronze/source=fsds/quarter={validate_quarter(quarter)}"


def zip_key(quarter: str) -> str:
    q = validate_quarter(quarter)
    return f"{bronze_prefix(q)}/{q}.zip"


def member_key(quarter: str, member: str) -> str:
    return f"{bronze_prefix(quarter)}/{member}"
