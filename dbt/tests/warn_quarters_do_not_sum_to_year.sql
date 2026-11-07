-- A finding about filer data, so it warns instead of failing. Quarters derived purely from
-- year-to-date figures sum to the annual figure by construction (Q1 + (H1 - Q1) + ...); a
-- gap beyond rounding means a filer's directly reported quarter disagrees with its own
-- year-to-date figures. Checks latest values against the latest annual figure.
{{ config(severity = 'warn') }}

with annual as (
    select
        reported.cik,
        reported.metric,
        reported.value_date as fiscal_year_end,
        reported.latest_value as annual_value
    from {{ ref('int_facts__versions') }} as reported
    inner join {{ ref('metrics') }} as metric_kinds
        on reported.metric = metric_kinds.metric
    where metric_kinds.kind = 'flow' and reported.duration_quarters = 4
),

summed as (
    select
        annual.cik,
        annual.metric,
        annual.fiscal_year_end,
        annual.annual_value,
        sum(quarters.latest_value) as quarters_total,
        count(*) as quarter_count
    from annual
    inner join {{ ref('int_facts__discrete_quarters') }} as quarters
        on
            annual.cik = quarters.cik
            and annual.metric = quarters.metric
            and dateadd(month, -12, annual.fiscal_year_end) < quarters.period_end
            and annual.fiscal_year_end >= quarters.period_end
    group by annual.cik, annual.metric, annual.fiscal_year_end, annual.annual_value
)

select
    cik,
    metric,
    fiscal_year_end,
    annual_value,
    quarters_total
from summed
where
    quarter_count = 4
    and abs(quarters_total - annual_value)
    > {{ var('restatement_threshold') }} * abs(annual_value)
