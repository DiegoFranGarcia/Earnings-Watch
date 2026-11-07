-- One row per company, metric and quarter end: a true three-month value for flows, and the
-- quarter-end balance for instants. 10-Q cash flows are year-to-date and most companies never
-- file a Q4 10-Q, so quarters are derived where needed: Q2 = H1 - Q1, Q3 = 9M - H1,
-- Q4 = FY - 9M. Both first-reported and latest values are derived the same way.
with reported_facts as (
    select
        reported.*,
        metric_kinds.kind
    from {{ ref('int_facts__versions') }} as reported
    inner join {{ ref('metrics') }} as metric_kinds
        on reported.metric = metric_kinds.metric
),

flows as (
    select * from reported_facts
    where kind = 'flow' and duration_quarters between 1 and 4
),

fiscal_position as (
    -- The longest flow ending on a date tells which fiscal quarter that date closes: a
    -- year-to-date figure there spans that many quarters (cash flow is always year-to-date).
    select
        cik,
        value_date,
        max(duration_quarters) as fiscal_quarter
    from flows
    group by cik, value_date
),

reported_directly as (
    select
        cik,
        metric,
        value_date,
        first_reported_value,
        latest_value,
        first_reported_at as first_known_at,
        latest_reported_at as latest_known_at,
        duration_quarters as source_duration_quarters,
        false as is_derived
    from flows
    where duration_quarters = 1
),

derived as (
    -- Year-to-date over d quarters, minus year-to-date over d - 1 quarters ending three
    -- months earlier. The SEC rounds every period end to a month end, so "three months
    -- earlier" is the last day of the month three months back.
    select
        year_to_date.cik,
        year_to_date.metric,
        year_to_date.value_date,
        year_to_date.duration_quarters as source_duration_quarters,
        true as is_derived,
        year_to_date.first_reported_value - earlier.first_reported_value
            as first_reported_value,
        year_to_date.latest_value - earlier.latest_value as latest_value,
        greatest(year_to_date.first_reported_at, earlier.first_reported_at) as first_known_at,
        greatest(year_to_date.latest_reported_at, earlier.latest_reported_at) as latest_known_at
    from flows as year_to_date
    inner join flows as earlier
        on
            year_to_date.cik = earlier.cik
            and year_to_date.metric = earlier.metric
            and earlier.duration_quarters = year_to_date.duration_quarters - 1
            and earlier.value_date = last_day(dateadd(month, -3, year_to_date.value_date))
    where year_to_date.duration_quarters >= 2
),

flow_candidates as (
    select
        cik,
        metric,
        value_date,
        first_reported_value,
        latest_value,
        first_known_at,
        latest_known_at,
        source_duration_quarters,
        is_derived
    from reported_directly
    union all
    select
        cik,
        metric,
        value_date,
        first_reported_value,
        latest_value,
        first_known_at,
        latest_known_at,
        source_duration_quarters,
        is_derived
    from derived
),

flow_quarters as (
    -- A directly reported quarter wins over a derived one; then the shortest derivation.
    -- Chosen after the union: a qualify inside it would apply to the last select only.
    select * from flow_candidates
    qualify row_number() over (
        partition by cik, metric, value_date
        order by is_derived, source_duration_quarters
    ) = 1
),

instant_quarters as (
    select
        cik,
        metric,
        value_date,
        first_reported_value,
        latest_value,
        first_reported_at as first_known_at,
        latest_reported_at as latest_known_at,
        duration_quarters as source_duration_quarters,
        false as is_derived
    from reported_facts
    where kind = 'instant' and duration_quarters = 0
),

quarters as (
    select * from flow_quarters
    union all
    select * from instant_quarters
)

select
    quarters.cik,
    quarters.metric,
    quarters.value_date as period_end,
    fiscal_position.fiscal_quarter,
    quarters.first_reported_value,
    quarters.latest_value,
    quarters.first_known_at,
    quarters.latest_known_at,
    quarters.source_duration_quarters,
    quarters.is_derived,
    -- The fiscal year is named after the calendar year in which it ends.
    year(last_day(dateadd(month, 3 * (4 - fiscal_position.fiscal_quarter), quarters.value_date)))
        as fiscal_year,
    md5(quarters.cik || '|' || quarters.metric || '|' || quarters.value_date) as quarter_key,
    abs(quarters.latest_value - quarters.first_reported_value)
    > {{ var('restatement_threshold') }} * abs(quarters.first_reported_value) as is_restated
from quarters
left join fiscal_position
    on
        quarters.cik = fiscal_position.cik
        and quarters.value_date = fiscal_position.value_date
