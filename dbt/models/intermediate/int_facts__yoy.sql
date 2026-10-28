-- One row per 10-Q or 10-K: year-to-date net income and operating cash flow,
-- each next to the same span a year earlier, plus total assets at period end.
with submissions as (
    select * from {{ ref('stg_sec__submissions') }}
),

facts as (
    select * from {{ ref('int_facts__canonical') }}
),

filings as (
    select
        *,
        -- A 10-Q's cash flow is year-to-date: Q1 covers 1 quarter, Q2 two, Q3 three.
        case fiscal_period
            when 'Q1' then 1
            when 'Q2' then 2
            when 'Q3' then 3
            when 'FY' then 4
        end as ytd_quarters
    from submissions
    where
        form in ('10-Q', '10-K')
        and fiscal_period in ('Q1', 'Q2', 'Q3', 'FY')
),

current_values as (
    select
        filings.accession_number,
        facts.metric,
        facts.value
    from filings
    inner join facts
        on
            filings.accession_number = facts.accession_number
            and filings.period_end = facts.value_date
            and facts.duration_quarters = case
                when facts.metric = 'total_assets' then 0   -- a balance: a point in time
                else filings.ytd_quarters
            end
),

prior_year_values as (
    -- The comparative column: same span, ending about twelve months earlier.
    -- Dates are rounded to month end, so allow one month either side.
    select
        filings.accession_number,
        facts.metric,
        facts.value
    from filings
    inner join facts
        on
            filings.accession_number = facts.accession_number
            and facts.metric != 'total_assets'
            and filings.ytd_quarters = facts.duration_quarters
            and facts.value_date
            between filings.period_end - interval '13 months'
            and filings.period_end - interval '11 months'
    qualify row_number() over (
        partition by filings.accession_number, facts.metric
        order by abs(datediff('day', facts.value_date, filings.period_end) - 365)
    ) = 1
),

-- Pivot each side to one row per filing before joining, so no join multiplies rows.
current_pivoted as (
    select
        accession_number,
        max(case when metric = 'net_income' then value end) as net_income,
        max(case when metric = 'operating_cash_flow' then value end) as operating_cash_flow,
        max(case when metric = 'total_assets' then value end) as total_assets
    from current_values
    group by accession_number
),

prior_year_pivoted as (
    select
        accession_number,
        max(case when metric = 'net_income' then value end) as net_income_prior_year,
        max(case when metric = 'operating_cash_flow' then value end)
            as operating_cash_flow_prior_year
    from prior_year_values
    group by accession_number
)

select
    filings.accession_number,
    filings.cik,
    filings.company_name,
    filings.sic,
    filings.form,
    filings.fiscal_year,
    filings.fiscal_period,
    filings.period_end,
    filings.filed_date,
    filings.ytd_quarters,
    current_pivoted.net_income,
    prior_year_pivoted.net_income_prior_year,
    current_pivoted.operating_cash_flow,
    prior_year_pivoted.operating_cash_flow_prior_year,
    current_pivoted.total_assets
from filings
left join current_pivoted
    on filings.accession_number = current_pivoted.accession_number
left join prior_year_pivoted
    on filings.accession_number = prior_year_pivoted.accession_number
