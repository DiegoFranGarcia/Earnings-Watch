"""EarningsWatch dashboard (the thin slice): one quarter, read from the dbt mart.

Run from the repository root:
    uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from earnings_screen import (
    SIC_DIVISIONS,
    comparison,
    database_path,
    edgar_filing_url,
    flagged,
    load_mart,
)

SIZE_FLOORS = {"Any size": 0.0, "$100M+": 1e8, "$1B+": 1e9, "$10B+": 1e10}
SCREENED_INDUSTRIES = [name for _, _, name in SIC_DIVISIONS if not name.startswith("Finance")]


@st.cache_data(show_spinner="Reading the mart...")
def _load(path: str, modified: float) -> pd.DataFrame:
    # `modified` is part of the cache key: after a dbt rebuild the file changes, so we reload.
    return load_mart(Path(path))


st.set_page_config(page_title="EarningsWatch", page_icon="🔎", layout="wide")
st.title("🔎 EarningsWatch")
st.write(
    "Companies whose **year-to-date net income rose** while **operating cash flow fell**, "
    "compared with the same span a year earlier. One quarter of SEC filings (2026 Q3)."
)
st.info(
    "A screen for where to look harder, **not investment advice**. A flag has many innocent "
    "explanations, such as a one-off gain or inventory built up ahead of growth.",
    icon="ℹ️",
)

path = database_path()
if not path.exists():
    st.error(f"No database at `{path}`. Build it first: `cd dbt && uv run dbt build`.")
    st.stop()

mart = _load(str(path), path.stat().st_mtime)

with st.sidebar:
    st.header("Filters")
    size = st.selectbox("Company size (total assets)", list(SIZE_FLOORS), index=2)
    industries = st.multiselect("Industries", SCREENED_INDUSTRIES, default=SCREENED_INDUSTRIES)
    st.caption(
        "Banks, insurers and filings with no industry code are not screened: "
        "operating cash flow means something different for them."
    )

shown = flagged(mart, SIZE_FLOORS[size], industries)

total, screened, all_flagged, in_view = st.columns(4)
total.metric("Filings compared", f"{len(mart):,}")
screened.metric("Screened", f"{int(mart['is_screened'].sum()):,}")
all_flagged.metric("Flagged", f"{int(mart['is_flagged'].sum()):,}")
in_view.metric("Flagged, with filters", f"{len(shown):,}")

st.subheader("Flagged filings")
table = pd.DataFrame(
    {
        "Company": shown["company_name"],
        "Industry": shown["industry"],
        "Period": shown["fiscal_period"] + " " + shown["fiscal_year"].astype(str),
        "Months": shown["months_covered"],
        "Net income, last year ($M)": shown["net_income_prior_year"] / 1e6,
        "Net income, this year ($M)": shown["net_income"] / 1e6,
        "Cash flow, last year ($M)": shown["operating_cash_flow_prior_year"] / 1e6,
        "Cash flow, this year ($M)": shown["operating_cash_flow"] / 1e6,
        "Accruals / assets": shown["accruals_to_assets"] * 100,
        "Profit multiple": shown["profit_multiple"],
    }
)
money = st.column_config.NumberColumn(format="%.0f")
st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "Net income, last year ($M)": money,
        "Net income, this year ($M)": money,
        "Cash flow, last year ($M)": money,
        "Cash flow, this year ($M)": money,
        "Accruals / assets": st.column_config.NumberColumn(format="%.1f%%"),
        "Profit multiple": st.column_config.NumberColumn(
            format="%.1f×", help="This year's net income divided by last year's."
        ),
    },
)

if shown.empty:
    st.warning("No flagged filings match these filters.")
    st.stop()

st.subheader("Look closer")
labels = (
    shown["company_name"] + " · " + shown["fiscal_period"] + " " + shown["fiscal_year"].astype(str)
).tolist()
choice = st.selectbox("Company", range(len(labels)), format_func=lambda i: labels[i])
row = shown.iloc[choice]

chart, facts = st.columns([3, 2])
with chart:
    st.bar_chart(
        comparison(row), x="metric", y="value_m", color="year", stack=False,
        x_label="", y_label="$ millions",
    )  # fmt: skip
with facts:
    st.markdown(
        f"**{row['company_name']}** · {row['form']} for {row['fiscal_period']} "
        f"{row['fiscal_year']}, covering **{row['months_covered']} months** "
        f"to {row['period_end']:%d %b %Y}, filed {row['filed_date']:%d %b %Y}."
    )
    st.metric("Accruals / total assets", f"{row['accruals_to_assets'] * 100:.1f}%")
    if pd.notna(row["profit_multiple"]) and row["profit_multiple"] >= 3:
        st.warning(
            f"Net income is {row['profit_multiple']:.1f}× last year's. A jump this size is often "
            "a one-off gain, such as selling a business, which this simple screen does not yet "
            "separate out."
        )
    st.link_button(
        "Open the filing on EDGAR", edgar_filing_url(row["cik"], row["accession_number"])
    )

st.caption(
    "Source: SEC Financial Statement Data Sets, 2026 Q3, as filed. "
    "Built with DuckDB, dbt and Streamlit."
)
