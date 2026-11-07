-- One row per 10-Q or 10-K that can be compared with a year earlier.
-- is_flagged: net income rose while operating cash flow fell over the same span.
with yoy as (
    select * from {{ ref('int_facts__yoy') }}
),

comparable as (
    select *
    from yoy
    where
        net_income is not null
        and net_income_prior_year is not null
        and operating_cash_flow is not null
        and operating_cash_flow_prior_year is not null
)

select
    accession_number,
    cik,
    company_name,
    sic,
    form,
    fiscal_year,
    fiscal_period,
    period_end,
    filed_date,
    net_income,
    net_income_prior_year,
    operating_cash_flow,
    operating_cash_flow_prior_year,
    total_assets,
    -- Subtraction widens DECIMAL(28,4) to (29,4); company figures sit far below that limit,
    -- so cast back to keep every money column the same type.
    cast(net_income - net_income_prior_year as decimal(28, 4)) as net_income_change,
    cast(operating_cash_flow - operating_cash_flow_prior_year as decimal(28, 4))
        as operating_cash_flow_change,
    -- Accruals: the part of profit not (yet) backed by cash.
    cast(net_income - operating_cash_flow as decimal(28, 4)) as accruals,
    -- A ratio, so a float everywhere: Snowflake would otherwise keep decimal division.
    cast((net_income - operating_cash_flow) / nullif(total_assets, 0) as double)
        as accruals_to_assets,
    ytd_quarters * 3 as months_covered,
    -- Banks and insurers (SIC 6000-6999): operating cash flow means something else there.
    coalesce(sic between 6000 and 6999, false) as is_financial,
    -- Screen only filings whose industry is known and not financial. Many investment funds
    -- carry no SIC code, and for a fund buying investments is an operating cash outflow.
    coalesce(sic is not null and sic not between 6000 and 6999, false) as is_screened,
    coalesce(
        sic is not null
        and sic not between 6000 and 6999
        and net_income > net_income_prior_year
        and operating_cash_flow < operating_cash_flow_prior_year,
        false
    ) as is_flagged
from comparable
