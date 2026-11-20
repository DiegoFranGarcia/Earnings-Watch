-- A finding about filer data, so it warns instead of failing (ADR 8), and the site shows it:
-- a year's net income or operating cash flow more than var implausible_multiple_of_assets times
-- the company's total assets is almost always a units mistake in the tagging (thousands taken
-- as units). The case that prompted it: Spectral Capital's net income for the year to
-- 2026-06-30 at $915m, on about $112m of assets, against $0.92m for its whole FY2025.
{{ config(severity = 'warn', store_failures = true) }}

select
    cik,
    company_name,
    reporting_view,
    period_end,
    ttm_net_income,
    ttm_operating_cash_flow,
    average_total_assets
from {{ ref('export_screener') }}
where is_implausible
