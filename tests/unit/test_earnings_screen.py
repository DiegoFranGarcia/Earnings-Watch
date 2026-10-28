"""Unit tests for the dashboard's data helpers and the app itself (no browser needed)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from earnings_screen import (
    comparison,
    edgar_filing_url,
    flagged,
    load_mart,
    profit_multiple,
    sic_division,
)

APP = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"

# name, sic, total assets, NI prior, NI now, CFO prior, CFO now, screened, flagged
FILINGS = [
    ("ALPHA CORP", 3674, 5e9, 200e6, 300e6, 180e6, 100e6, True, True),
    ("GAMMA LTD", 5812, 2e8, 50e6, 80e6, 40e6, 10e6, True, True),
    ("BETA INC", 2810, 5e9, 400e6, 500e6, 500e6, 600e6, True, False),
    ("EPSILON BANK", 6021, 9e9, 30e6, 40e6, 20e6, 5e6, False, False),
]


def make_mart(path: Path) -> Path:
    """A tiny mart_earnings_quality with the real column names and types."""
    rows = ", ".join(
        f"('000000000{i}-26-000001', {i}, '{name}', {sic}, '10-Q', 2026, 'Q2', DATE '2026-06-30',"
        f" DATE '2026-08-05', 6, {ni}, {ni_prior}, {cfo}, {cfo_prior}, {assets},"
        f" {(ni - cfo) / assets}, {sic // 100 in range(60, 68)}, {screened}, {flag})"
        for i, (name, sic, assets, ni_prior, ni, cfo_prior, cfo, screened, flag) in enumerate(
            FILINGS, start=1
        )
    )
    with duckdb.connect(str(path)) as con:
        con.execute(f"""
            CREATE TABLE main.mart_earnings_quality AS
            SELECT * FROM (VALUES {rows}) AS t(
                accession_number, cik, company_name, sic, form, fiscal_year, fiscal_period,
                period_end, filed_date, months_covered, net_income, net_income_prior_year,
                operating_cash_flow, operating_cash_flow_prior_year, total_assets,
                accruals_to_assets, is_financial, is_screened, is_flagged
            )
        """)  # noqa: S608 - test fixture built from constants
    return path


@pytest.fixture
def mart_path(tmp_path: Path) -> Path:
    return make_mart(tmp_path / "earningswatch.duckdb")


# -- helpers --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sic", "expected"),
    [
        (3674, "Manufacturing"),
        (5812, "Retail trade"),
        (6021, "Finance, insurance & real estate"),
        (7372, "Services"),
        (None, "Unknown"),
        (pd.NA, "Unknown"),
    ],
)
def test_sic_division(sic, expected) -> None:
    assert sic_division(sic) == expected


def test_profit_multiple_needs_a_prior_profit() -> None:
    result = profit_multiple(pd.Series([300.0, 50.0, 10.0]), pd.Series([100.0, 0.0, -20.0]))
    assert result.iloc[0] == 3.0
    assert result.iloc[1:].isna().all(), "no multiple of a zero or a loss"


def test_load_mart_adds_industry_and_releases_the_file(mart_path: Path) -> None:
    frame = load_mart(mart_path)

    assert len(frame) == len(FILINGS)
    assert frame.set_index("company_name").loc["ALPHA CORP", "industry"] == "Manufacturing"
    # The file must be free again, so dbt could write to it while the app is running.
    with duckdb.connect(str(mart_path)) as writer:
        writer.execute("CREATE TABLE main.proof_of_no_lock AS SELECT 1 AS x")


def test_flagged_filters_and_sorts(mart_path: Path) -> None:
    frame = load_mart(mart_path)

    big = flagged(frame, 1e9, ["Manufacturing", "Retail trade"])
    assert big["company_name"].tolist() == ["ALPHA CORP"]

    every_size = flagged(frame, 0, ["Manufacturing", "Retail trade"])
    assert every_size["company_name"].tolist() == ["GAMMA LTD", "ALPHA CORP"]  # highest first


def test_comparison_is_in_millions(mart_path: Path) -> None:
    row = load_mart(mart_path).set_index("company_name").loc["ALPHA CORP"]

    chart = comparison(row)

    assert chart.to_dict("records") == [
        {"metric": "Net income", "year": "Last year", "value_m": 200.0},
        {"metric": "Net income", "year": "This year", "value_m": 300.0},
        {"metric": "Operating cash flow", "year": "Last year", "value_m": 180.0},
        {"metric": "Operating cash flow", "year": "This year", "value_m": 100.0},
    ]


def test_edgar_url() -> None:
    assert edgar_filing_url(2488, "0000002488-26-000123") == (
        "https://www.sec.gov/Archives/edgar/data/2488/000000248826000123/"
    )


# -- the app, run headless ---------------------------------------------------------


def test_app_renders_the_screen(mart_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EW_DUCKDB_PATH", str(mart_path))

    app = AppTest.from_file(str(APP), default_timeout=30).run()

    assert not app.exception
    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics["Filings compared"] == "4"
    assert metrics["Screened"] == "3"
    assert metrics["Flagged"] == "2"
    assert metrics["Flagged, with filters"] == "1"  # the default size filter is $1B+
    assert app.dataframe[0].value["Company"].tolist() == ["ALPHA CORP"]


def test_app_size_filter_changes_the_view(mart_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EW_DUCKDB_PATH", str(mart_path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()

    app.sidebar.selectbox[0].set_value("Any size").run()

    assert not app.exception
    assert app.dataframe[0].value["Company"].tolist() == ["GAMMA LTD", "ALPHA CORP"]


def test_app_explains_a_missing_database(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EW_DUCKDB_PATH", str(tmp_path / "missing.duckdb"))

    app = AppTest.from_file(str(APP), default_timeout=30).run()

    assert not app.exception
    assert "dbt build" in app.error[0].value
