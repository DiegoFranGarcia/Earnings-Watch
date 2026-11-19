-- The company page: each screener company's quarterly net income and operating cash flow since
-- var site_first_quarter, as first reported and latest, with what was restated or derived from
-- year-to-date figures. One row per company and quarter end. Part of the site's export
-- contract (ADR 17).
with screener_companies as (
    select distinct cik from {{ ref('export_screener') }}
),

quarters as (
    select * from {{ ref('fct_company_quarter_metrics') }}
    where
        metric in ('net_income', 'operating_cash_flow')
        and period_end >= '{{ var("site_first_quarter") }}'
        and cik in (select screener_companies.cik from screener_companies)
)

select
    cik,
    period_end,
    any_value(fiscal_year) as fiscal_year,
    any_value(fiscal_quarter) as fiscal_quarter,
    max(iff(metric = 'net_income', first_reported_value, null)) as net_income_first_reported,
    max(iff(metric = 'net_income', latest_value, null)) as net_income_latest,
    max(iff(metric = 'operating_cash_flow', first_reported_value, null))
        as operating_cash_flow_first_reported,
    max(iff(metric = 'operating_cash_flow', latest_value, null)) as operating_cash_flow_latest,
    coalesce(boolor_agg(iff(metric = 'net_income', is_restated, null)), false)
        as is_net_income_restated,
    coalesce(boolor_agg(iff(metric = 'operating_cash_flow', is_restated, null)), false)
        as is_operating_cash_flow_restated,
    coalesce(boolor_agg(is_derived), false) as is_derived,
    cik || '|' || period_end as company_quarter_key
from quarters
group by cik, period_end
