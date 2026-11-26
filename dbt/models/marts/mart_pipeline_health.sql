-- One row per complete UTC day of the pipeline's life, from pipeline_started_on to yesterday (this
-- model is built inside the morning's dbt_build, before that morning's export runs, so today is
-- never complete): its whole record, not a window. Was a run expected, did the export
-- finish by 09:00 UTC, is the data correct, complete and fresh, and what did it cost? Correct:
-- dbt test results (warnings are documented findings about filer data, so only failures lower
-- the pass rate). Complete: the volume gate's checks. Fresh: the newest day of the daily index
-- each gate saw, recorded at the time (RAW's own load times are overwritten by every reload, so
-- only the gate's records keep the history). Cost: the cost mart, which lags by up to six hours.
--
-- Only the pipeline's own runs count: Airflow's run IDs (scheduled__, asset_triggered__,
-- manual__, backfill__). dbt run from a laptop (run label "manual" or "manual-<time>") and drills
-- (run IDs starting manual__drill-) are left out of every figure; a drill only sets has_drill.
-- Every timestamp used here is UTC (SYSDATE(), or Airflow's API times converted to UTC), and
-- "today" is the UTC date, not the Snowflake session's. pipeline_run() is in macros/.

with as_of as (
    select coalesce(
        try_to_date('{{ var("pipeline_health_as_of", "") }}'),
        cast(convert_timezone('UTC', current_timestamp()) as date)
    ) as today
),

days as (
    select dim_date.date_day
    from {{ ref('dim_date') }} as dim_date
    cross join as_of
    where
        dim_date.date_day
        between cast('{{ var("pipeline_started_on") }}' as date) and dateadd(day, -1, as_of.today)
),

calendar as (
    select * from {{ ref('int_sec_calendar') }}
),

dbt_results as (
    select * from {{ source('audit', 'dbt_results') }}
    where {{ pipeline_run('run_label') }}
),

dq_results as (
    select * from {{ source('audit', 'dq_results') }}
),

task_attempts as (
    select * from {{ source('audit', 'airflow_task_attempts') }}
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
        count_if({{ pipeline_run('run_id') }}) as volume_checks,
        count_if({{ pipeline_run('run_id') }} and outcome = 'fail') as volume_failures,
        max(iff(
            {{ pipeline_run('run_id') }} and check_name = 'daily_filings',
            try_to_date(subject), null
        )) as latest_index_day,
        count_if(startswith(run_id, 'manual__drill-')) > 0 as has_drill
    from dq_results
    group by date_day
),

-- Each task's last try decides how it ended (a failed try a retry recovered is not a failure).
task_outcomes as (
    select
        dag_id,
        run_id,
        task_id,
        state,
        started_at,
        ended_at
    from task_attempts
    where {{ pipeline_run('run_id') }}
    qualify row_number() over (
        partition by dag_id, run_id, task_id, map_index order by try_number desc
    ) = 1
),

task_days as (
    select
        cast(started_at as date) as date_day,
        count(*) as data_chain_tasks,
        count_if(state = 'failed') > 0 as has_failed_task
    from task_outcomes
    -- The DAGs that land, load, build and export the data; record_task_history is not one, and
    -- check_landed_days reports an earlier day's gap, not a failure of this day's run.
    where
        dag_id in (
            'sec_daily_index', 'sec_fsds_quarterly', 'snowflake_load',
            'snowflake_load_daily_index', 'dbt_build', 'publish_site'
        )
        and task_id <> 'check_landed_days'
    group by date_day
),

export_days as (
    select
        cast(ended_at as date) as date_day,
        min(ended_at) as first_exported_at
    from task_outcomes
    where dag_id = 'publish_site' and task_id = 'export' and state = 'success'
    group by date_day
),

-- The record begins on the first day the task history holds a run of the export (publish_site):
-- before it, the export did not exist yet (it was added on 2026-11-18, after that morning's run)
-- or its runs were not recorded, so those days are "not recorded" rather than counted as misses.
-- The history records at 09:30 UTC, so a day is complete in it only once a recording after its
-- end exists: until then a day that neither met its target nor was held is "not recorded" yet,
-- not failed or missed.
recorded_since as (
    select
        min(iff(
            dag_id = 'publish_site' and {{ pipeline_run('run_id') }},
            cast(started_at as date), null
        )) as first_day,
        max(recorded_at) as last_recorded_at
    from task_attempts
),

cost_days as (
    select
        cast(started_at as date) as date_day,
        sum(dollars) as dollars
    from costs
    where {{ pipeline_run('run_id') }}
    group by date_day
),

daily as (
    select
        days.date_day,
        volume_days.latest_index_day,
        export_days.first_exported_at,
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
        datediff(day, volume_days.latest_index_day, days.date_day) as index_lag_days,
        -- Each morning's run fetches the day before's index: a run is due when that was a
        -- business day at EDGAR.
        coalesce(calendar.is_business_day, false) as run_expected,
        coalesce(
            export_days.first_exported_at <= dateadd(hour, 9, cast(days.date_day as timestamp_ntz)),
            false
        ) as exported_by_target,
        coalesce(test_days.tests_failed, 0) + coalesce(test_days.models_failed, 0)
        + coalesce(volume_days.volume_failures, 0) > 0 as has_failed_check,
        coalesce(task_days.has_failed_task, false) as has_failed_task,
        coalesce(volume_days.has_drill, false) as has_drill,
        recorded_since.first_day is null or days.date_day < recorded_since.first_day
            as before_record,
        coalesce(
            recorded_since.last_recorded_at
            >= dateadd(day, 1, cast(days.date_day as timestamp_ntz)),
            false
        ) as task_history_complete
    from days
    cross join recorded_since
    left join calendar on calendar.calendar_date = dateadd(day, -1, days.date_day)
    left join test_days on days.date_day = test_days.date_day
    left join volume_days on days.date_day = volume_days.date_day
    left join task_days on days.date_day = task_days.date_day
    left join export_days on days.date_day = export_days.date_day
    left join cost_days on days.date_day = cost_days.date_day
)

select
    date_day,
    latest_index_day,
    dbt_invocations,
    tests_run,
    tests_passed,
    tests_warned,
    tests_failed,
    models_failed,
    test_pass_rate,
    volume_checks,
    volume_failures,
    dollars,
    index_lag_days,
    run_expected,
    first_exported_at,
    exported_by_target,
    has_failed_check,
    has_failed_task,
    has_drill,
    -- The first that applies wins.
    case
        when not run_expected then 'no_run_expected'
        when before_record then 'not_recorded'
        when exported_by_target and not has_failed_check then 'met'
        when has_failed_check then 'held'
        when first_exported_at is not null then 'late'
        when not task_history_complete then 'not_recorded'
        when has_failed_task then 'failed'
        else 'missed'
    end as day_state
from daily
