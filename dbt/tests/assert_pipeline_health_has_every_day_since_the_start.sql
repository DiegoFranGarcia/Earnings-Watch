-- The Pipeline page reads the pipeline's whole record: one row per UTC day, no gaps, from
-- pipeline_started_on to yesterday in UTC (the model is built before the morning's export, so
-- today is never complete). Snowflake's session runs in America/Los_Angeles, where current_date()
-- at the 06:00 UTC build is still the day before: a day list built on it was a day behind (found
-- 2026-11-24). An empty table fails too: the bounds come from the settings, not from the rows.
with bounds as (
    select
        cast('{{ var("pipeline_started_on") }}' as date) as first_day,
        dateadd(day, -1, cast(convert_timezone('UTC', current_timestamp()) as date)) as last_day
)

select
    bounds.first_day as expected_first_day,
    bounds.last_day as expected_last_day,
    count(health.date_day) as days,
    min(health.date_day) as first_day,
    max(health.date_day) as last_day
from bounds
left join {{ ref('mart_pipeline_health') }} as health on true
group by bounds.first_day, bounds.last_day
having
    count(health.date_day) <> datediff(day, bounds.first_day, bounds.last_day) + 1
    or count(distinct health.date_day) <> count(health.date_day)
    or min(health.date_day) is distinct from bounds.first_day
    or max(health.date_day) is distinct from bounds.last_day
