-- The screener page: each company still filing, at its most recent screened quarter, in both
-- reporting views, with its industry and filer size. Part of the public site's export contract
-- (ADR 17): only what the page shows. "Still filing" means the quarter became knowable within
-- var site_recent_months of the newest data in the warehouse, not of the build's date: the
-- screener changes only when new SEC data does, so every build of the same data gives the same
-- companies (on 2026-11-21 one aged out overnight, with no new data, and its company pages,
-- still in yesterday's tables, failed their relationship tests).
with newest as (
    select max(known_at)::date as newest_known_on
    from {{ ref('mart_earnings_quality') }}
),

quarters as (
    -- Aliased: in a dbt unit test the ref is a CTE with another name.
    select quality.*
    from {{ ref('mart_earnings_quality') }} as quality
    cross join newest
    where
        quality.is_screened
        and quality.known_at
        >= dateadd(month, -{{ var('site_recent_months') }}, newest.newest_known_on)
),

latest as (
    select * from quarters
    qualify row_number() over (partition by cik, reporting_view order by period_end desc) = 1
),

companies as (
    select
        cik,
        company_name,
        filer_status
    from {{ ref('dim_company') }}
    where is_current
),

filer_groups as (
    -- One group per filer status (the seed repeats it per form).
    select distinct
        filer_status,
        filer_group
    from {{ ref('filing_deadlines') }}
),

industries as (
    select * from {{ ref('stg_sec__sic_codes') }}
)

select
    latest.cik,
    latest.reporting_view,
    latest.period_end,
    latest.fiscal_year,
    latest.fiscal_quarter,
    latest.known_at,
    latest.sic,
    industries.industry_title,
    companies.filer_status,
    latest.ttm_net_income,
    latest.prior_ttm_net_income,
    latest.ttm_operating_cash_flow,
    latest.prior_ttm_operating_cash_flow,
    latest.average_total_assets,
    latest.accruals,
    latest.accruals_to_assets,
    latest.is_flagged,
    -- Figures no ordinary company reports, usually a units mistake in the filing: shown with a
    -- warning, not dropped (ADR 8; warn_screener_figures_look_implausible lists them).
    coalesce(
        abs(latest.ttm_net_income)
        > {{ var('implausible_multiple_of_assets') }} * latest.average_total_assets
        or abs(latest.ttm_operating_cash_flow)
        > {{ var('implausible_multiple_of_assets') }} * latest.average_total_assets,
        false
    ) as is_implausible,
    -- The current name, so a renamed company is shown as it is known today.
    coalesce(companies.company_name, latest.company_name) as company_name,
    coalesce(industries.industry_group, 'Unknown') as industry_group,
    coalesce(filer_groups.filer_group, 'unknown') as filer_group,
    latest.cik || '|' || latest.reporting_view as screener_key
from latest
left join companies on latest.cik = companies.cik
left join filer_groups on companies.filer_status = filer_groups.filer_status
left join industries on latest.sic = industries.sic
