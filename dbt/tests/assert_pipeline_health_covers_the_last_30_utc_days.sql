-- The pipeline page reads one row per complete UTC day, the last 30, ending yesterday in UTC
-- (the model is built before the morning's export, so today is never complete). Snowflake's
-- session runs in America/Los_Angeles, where current_date() at the 06:00 UTC build is still the
-- day before: a day list built on it was a day behind (found 2026-11-24).
select
    count(*) as days,
    min(date_day) as first_day,
    max(date_day) as last_day
from {{ ref('mart_pipeline_health') }}
having
    count(*) <> 30
    or count(distinct date_day) <> 30
    or max(date_day) <> dateadd(day, -1, convert_timezone('UTC', current_timestamp())::date)
    or min(date_day) <> dateadd(day, -30, convert_timezone('UTC', current_timestamp())::date)
