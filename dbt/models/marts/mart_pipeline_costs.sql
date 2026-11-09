-- One row per platform, pipeline step and Airflow run: what it cost, in dollars at the prices in
-- dbt_project.yml. Snowflake: the credits attributed to every query whose tag is
-- earningswatch:<step>:<run id>, which every load, gate and dbt statement carries. EMR: what it
-- billed for each Spark job. Snowflake's attribution excludes warehouse idle time (the 60 seconds
-- before auto-suspend) and lags by up to six hours, so recent runs appear late and costs are a
-- slight understatement of the bill.
with snowflake_queries as (
    select * from {{ source('snowflake_usage', 'query_attribution_history') }}
    where query_tag like 'earningswatch:%'
),

emr_jobs as (
    select * from {{ source('audit', 'emr_job_runs') }}
),

tagged_queries as (
    select
        credits_attributed_compute,
        -- The run ID itself contains colons (its timestamp), so take everything after the
        -- second colon rather than splitting on every colon.
        regexp_substr(query_tag, '^earningswatch:([^:]+):', 1, 1, 'e') as pipeline_step,
        regexp_substr(query_tag, '^earningswatch:[^:]+:(.*)$', 1, 1, 'e') as run_id,
        convert_timezone('UTC', start_time) as started_at,
        convert_timezone('UTC', end_time) as ended_at
    from snowflake_queries
),

snowflake_costs as (
    select
        'snowflake' as platform,
        pipeline_step,
        run_id,
        'credits' as usage_unit,
        min(started_at) as started_at,
        max(ended_at) as ended_at,
        count(*) as query_count,
        sum(credits_attributed_compute) as usage_amount,
        sum(credits_attributed_compute) * {{ var('snowflake_dollars_per_credit') }} as dollars
    from tagged_queries
    group by pipeline_step, run_id
),

emr_costs as (
    select
        'emr' as platform,
        'spark' as pipeline_step,
        run_id,
        'vcpu_hours' as usage_unit,
        min(recorded_at) as started_at,
        max(recorded_at) as ended_at,
        count(*) as query_count,
        sum(vcpu_hours) as usage_amount,
        sum(
            vcpu_hours * {{ var('emr_dollars_per_vcpu_hour') }}
            + memory_gb_hours * {{ var('emr_dollars_per_gb_hour') }}
            + storage_gb_hours * {{ var('emr_dollars_per_storage_gb_hour') }}
        ) as dollars
    from emr_jobs
    group by run_id
),

costs as (
    select * from snowflake_costs
    union all
    select * from emr_costs
)

select
    platform,
    pipeline_step,
    run_id,
    usage_unit,
    query_count,
    cast(started_at as timestamp_ntz) as started_at,
    cast(ended_at as timestamp_ntz) as ended_at,
    cast(usage_amount as double) as usage_amount,
    cast(dollars as decimal(18, 6)) as dollars,
    md5(platform || '|' || pipeline_step || '|' || run_id) as cost_key
from costs
