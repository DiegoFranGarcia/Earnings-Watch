-- One row per day for the last 30 days: is the data correct, complete and fresh, and what did
-- it cost? Correct: dbt test results (warnings are documented findings about filer data, so
-- only failures lower the pass rate). Complete: the volume gate's checks. Fresh: the newest
-- day of the daily index each gate saw, recorded at the time (RAW's own load times are
-- overwritten by every reload, so only the gate's records keep the history). Cost: the cost
-- mart, which lags by up to six hours.
with days as (
    select date_day from {{ ref('dim_date') }}
    where date_day between dateadd(day, -29, current_date()) and current_date()
),

dbt_results as (
    select * from {{ source('audit', 'dbt_results') }}
),

dq_results as (
    select * from {{ source('audit', 'dq_results') }}
),

costs as (
    select * from {{ ref('mart_pipeline_costs') }}
),

test_days as (
    select
        cast(recorded_at as date) as date_day,
        count(distinct invocation_id) as dbt_invocations,
        count_if(resource_type in ('test', 'unit_test')) as tests_run,
        count_if(resource_type in ('test', 'unit_test') and status = 'pass') as tests_passed,
        count_if(resource_type in ('test', 'unit_test') and status = 'warn') as tests_warned,
        count_if(resource_type in ('test', 'unit_test') and status in ('fail', 'error'))
            as tests_failed,
        count_if(resource_type in ('model', 'seed') and status = 'error') as models_failed
    from dbt_results
    group by date_day
),

volume_days as (
    select
        cast(checked_at as date) as date_day,
        count(*) as volume_checks,
        count_if(outcome = 'fail') as volume_failures,
        max(iff(check_name = 'daily_filings', try_to_date(subject), null)) as latest_index_day
    from dq_results
    group by date_day
),

cost_days as (
    select
        cast(started_at as date) as date_day,
        sum(dollars) as dollars
    from costs
    group by date_day
)

select
    days.date_day,
    volume_days.latest_index_day,
    cast(coalesce(test_days.dbt_invocations, 0) as integer) as dbt_invocations,
    cast(coalesce(test_days.tests_run, 0) as integer) as tests_run,
    cast(coalesce(test_days.tests_passed, 0) as integer) as tests_passed,
    cast(coalesce(test_days.tests_warned, 0) as integer) as tests_warned,
    cast(coalesce(test_days.tests_failed, 0) as integer) as tests_failed,
    cast(coalesce(test_days.models_failed, 0) as integer) as models_failed,
    cast(
        1 - test_days.tests_failed / nullif(test_days.tests_run, 0) as double
    ) as test_pass_rate,
    cast(coalesce(volume_days.volume_checks, 0) as integer) as volume_checks,
    cast(coalesce(volume_days.volume_failures, 0) as integer) as volume_failures,
    cast(coalesce(cost_days.dollars, 0) as decimal(18, 6)) as dollars,
    datediff(day, volume_days.latest_index_day, days.date_day) as index_lag_days
from days
left join test_days on days.date_day = test_days.date_day
left join volume_days on days.date_day = volume_days.date_day
left join cost_days on days.date_day = cost_days.date_day
