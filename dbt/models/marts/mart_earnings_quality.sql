-- One row per company, quarter end and reporting view: trailing-twelve-month (TTM) net income
-- and operating cash flow against the year before, and accruals as a share of average total
-- assets. Flagged when income rose, cash did not, and accruals are large. Two views of every
-- quarter: as first reported (only what was published at the time, so no look-ahead bias)
-- and latest (restatements applied). A screen for where to look harder, not advice.
with quarters as (
    select * from {{ ref('fct_company_quarter_metrics') }}
    where metric in ('net_income', 'operating_cash_flow', 'total_assets')
),

companies as (
    select * from {{ ref('dim_company') }}
),

by_view as (
    -- Each quarter's values twice, so one calculation below serves both views.
    select
        cik,
        company_key,
        period_end,
        fiscal_year,
        fiscal_quarter,
        metric,
        first_reported_value as metric_value,
        first_known_at as known_at,
        'first_reported' as reporting_view
    from quarters
    union all
    select
        cik,
        company_key,
        period_end,
        fiscal_year,
        fiscal_quarter,
        metric,
        latest_value as metric_value,
        latest_known_at as known_at,
        'latest' as reporting_view
    from quarters
),

company_quarters as (
    select
        cik,
        reporting_view,
        period_end,
        any_value(fiscal_year) as fiscal_year,
        any_value(fiscal_quarter) as fiscal_quarter,
        max(iff(metric = 'net_income', company_key, null)) as company_key,
        max(iff(metric = 'net_income', metric_value, null)) as net_income,
        max(iff(metric = 'operating_cash_flow', metric_value, null)) as operating_cash_flow,
        max(iff(metric = 'total_assets', metric_value, null)) as total_assets,
        max(known_at) as known_at
    from by_view
    group by cik, reporting_view, period_end
),

trailing_year as (
    -- The four quarters ending on or within twelve months before this one.
    select
        this_quarter.cik,
        this_quarter.reporting_view,
        this_quarter.period_end,
        any_value(this_quarter.fiscal_year) as fiscal_year,
        any_value(this_quarter.fiscal_quarter) as fiscal_quarter,
        any_value(this_quarter.company_key) as company_key,
        any_value(this_quarter.total_assets) as total_assets,
        sum(window_quarter.net_income) as ttm_net_income,
        sum(window_quarter.operating_cash_flow) as ttm_operating_cash_flow,
        count(window_quarter.net_income) as net_income_quarters,
        count(window_quarter.operating_cash_flow) as cash_flow_quarters,
        max(window_quarter.known_at) as known_at
    from company_quarters as this_quarter
    inner join company_quarters as window_quarter
        on
            this_quarter.cik = window_quarter.cik
            and this_quarter.reporting_view = window_quarter.reporting_view
            and dateadd(month, -12, this_quarter.period_end) < window_quarter.period_end
            and this_quarter.period_end >= window_quarter.period_end
    group by this_quarter.cik, this_quarter.reporting_view, this_quarter.period_end
),

complete_years as (
    -- Only full years: four quarters of both net income and operating cash flow.
    select * from trailing_year
    where net_income_quarters = 4 and cash_flow_quarters = 4
),

compared as (
    select
        this_year.cik,
        this_year.reporting_view,
        this_year.period_end,
        this_year.fiscal_year,
        this_year.fiscal_quarter,
        this_year.company_key,
        this_year.ttm_net_income,
        this_year.ttm_operating_cash_flow,
        prior_year.ttm_net_income as prior_ttm_net_income,
        prior_year.ttm_operating_cash_flow as prior_ttm_operating_cash_flow,
        -- Average of the balances a year apart where both exist, else whichever exists.
        coalesce(
            (this_year.total_assets + prior_year.total_assets) / 2,
            this_year.total_assets,
            prior_year.total_assets
        ) as average_total_assets,
        greatest(this_year.known_at, prior_year.known_at) as known_at
    from complete_years as this_year
    inner join complete_years as prior_year
        on
            this_year.cik = prior_year.cik
            and this_year.reporting_view = prior_year.reporting_view
            and last_day(dateadd(month, -12, this_year.period_end)) = prior_year.period_end
),

measured as (
    select
        compared.*,
        companies.company_name,
        companies.sic,
        -- Accruals scaled by size, so a small company's small gap can matter as much as a
        -- large company's large one.
        cast(
            (compared.ttm_net_income - compared.ttm_operating_cash_flow)
            / nullif(compared.average_total_assets, 0) as double
        ) as accruals_to_assets,
        compared.ttm_net_income - compared.ttm_operating_cash_flow as accruals,
        coalesce(companies.sic between 6000 and 6999, false) as is_financial
    from compared
    left join companies
        on compared.company_key = companies.company_key
)

select
    cik,
    company_key,
    company_name,
    sic,
    reporting_view,
    period_end,
    fiscal_year,
    fiscal_quarter,
    known_at,
    is_financial,
    accruals_to_assets,
    cast(ttm_net_income as decimal(30, 4)) as ttm_net_income,
    cast(prior_ttm_net_income as decimal(30, 4)) as prior_ttm_net_income,
    cast(ttm_operating_cash_flow as decimal(30, 4)) as ttm_operating_cash_flow,
    cast(prior_ttm_operating_cash_flow as decimal(30, 4)) as prior_ttm_operating_cash_flow,
    cast(average_total_assets as decimal(30, 4)) as average_total_assets,
    cast(accruals as decimal(30, 4)) as accruals,
    md5(cik || '|' || period_end || '|' || reporting_view) as earnings_quality_key,
    -- Screened: industry known, not financial (banks' cash flows follow other rules), and big
    -- enough for the ratio to mean something. A size that cannot be measured is not screened.
    coalesce(
        sic is not null
        and not is_financial
        and average_total_assets >= {{ var('minimum_average_assets') }},
        false
    ) as is_screened,
    -- Always true or false: a comparison with a missing value must not make the flag unknown.
    coalesce(
        sic is not null
        and not is_financial
        and average_total_assets >= {{ var('minimum_average_assets') }}
        and ttm_net_income > prior_ttm_net_income
        and ttm_operating_cash_flow <= prior_ttm_operating_cash_flow
        and accruals_to_assets > {{ var('accrual_ratio_threshold') }},
        false
    ) as is_flagged
from measured
