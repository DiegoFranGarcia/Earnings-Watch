-- The pipeline-health page: the whole mart, one row per day for the last 30 days (tests,
-- volume checks, freshness and cost). Part of the site's export contract (ADR 17).
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
    dollars
from {{ ref('mart_pipeline_health') }}
