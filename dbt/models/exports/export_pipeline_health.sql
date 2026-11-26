-- The Pipeline page: the whole mart, one row per complete UTC day from pipeline_started_on to
-- yesterday, the pipeline's whole record (tests, volume checks, freshness, the export's time, the
-- day's state and cost). Part of the site's export contract (ADR 17).
select
    date_day,
    latest_index_day,
    index_lag_days,
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
    run_expected,
    first_exported_at,
    exported_by_target,
    has_failed_check,
    has_failed_task,
    has_drill,
    day_state
from {{ ref('mart_pipeline_health') }}
