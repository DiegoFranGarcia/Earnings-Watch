"""Data helpers for the EarningsWatch dashboard.

No Streamlit calls live here, so everything can be unit-tested; streamlit_app.py only
draws. The dashboard reads the mart and nothing else, so it never depends on how the
data was built.
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import pandas as pd

DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data" / "earningswatch.duckdb"

# The official SIC divisions, by the first two digits of the code.
SIC_DIVISIONS = (
    (1, 9, "Agriculture, forestry & fishing"),
    (10, 14, "Mining"),
    (15, 17, "Construction"),
    (20, 39, "Manufacturing"),
    (40, 49, "Transportation, communications & utilities"),
    (50, 51, "Wholesale trade"),
    (52, 59, "Retail trade"),
    (60, 67, "Finance, insurance & real estate"),
    (70, 89, "Services"),
    (91, 99, "Public administration & other"),
)
UNKNOWN_INDUSTRY = "Unknown"

# Money arrives as DECIMAL(28,4) for exactness; the dashboard only displays it, so float is fine.
MART_QUERY = """
    SELECT
        accession_number, cik, company_name, sic, form, fiscal_year, fiscal_period,
        period_end, filed_date, months_covered,
        CAST(net_income AS DOUBLE) AS net_income,
        CAST(net_income_prior_year AS DOUBLE) AS net_income_prior_year,
        CAST(operating_cash_flow AS DOUBLE) AS operating_cash_flow,
        CAST(operating_cash_flow_prior_year AS DOUBLE) AS operating_cash_flow_prior_year,
        CAST(total_assets AS DOUBLE) AS total_assets,
        accruals_to_assets, is_financial, is_screened, is_flagged
    FROM main.mart_earnings_quality
"""


def database_path() -> Path:
    """Where the mart lives; EW_DUCKDB_PATH overrides the default (tests use this)."""
    return Path(os.environ.get("EW_DUCKDB_PATH", str(DEFAULT_DATABASE)))


def sic_division(sic: object) -> str:
    """Name the broad industry for a four-digit SIC code."""
    if sic is None or pd.isna(sic):
        return UNKNOWN_INDUSTRY
    major_group = int(sic) // 100
    for low, high, name in SIC_DIVISIONS:
        if low <= major_group <= high:
            return name
    return UNKNOWN_INDUSTRY


def profit_multiple(current: pd.Series, prior: pd.Series) -> pd.Series:
    """This year's net income as a multiple of last year's; only defined for a prior profit."""
    return (current / prior).where(prior > 0)


def load_mart(path: Path) -> pd.DataFrame:
    """Read the mart into memory, then let go of the file.

    DuckDB allows one writer at a time, so the dashboard never holds the database open:
    `dbt build` can always run while the app is up.
    """
    with duckdb.connect(str(path), read_only=True) as con:
        frame = con.execute(MART_QUERY).df()
    frame["industry"] = frame["sic"].map(sic_division)
    frame["profit_multiple"] = profit_multiple(frame["net_income"], frame["net_income_prior_year"])
    return frame


def flagged(frame: pd.DataFrame, min_assets: float, industries: list[str]) -> pd.DataFrame:
    """Flagged filings that pass the filters, biggest accruals relative to assets first."""
    keep = (
        frame["is_flagged"]
        & (frame["total_assets"].fillna(0) >= min_assets)
        & frame["industry"].isin(industries)
    )
    return frame[keep].sort_values("accruals_to_assets", ascending=False)


def comparison(row: pd.Series) -> pd.DataFrame:
    """Net income and operating cash flow, last year against this year, in $ millions."""
    pairs = (
        ("Net income", "net_income_prior_year", "net_income"),
        ("Operating cash flow", "operating_cash_flow_prior_year", "operating_cash_flow"),
    )
    records = []
    for metric, prior, current in pairs:
        records.append({"metric": metric, "year": "Last year", "value_m": row[prior] / 1e6})
        records.append({"metric": metric, "year": "This year", "value_m": row[current] / 1e6})
    return pd.DataFrame(records)


def edgar_filing_url(cik: int, accession_number: str) -> str:
    """The filing's folder on EDGAR, so every figure can be traced to its source."""
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_number.replace('-', '')}/"
    )
