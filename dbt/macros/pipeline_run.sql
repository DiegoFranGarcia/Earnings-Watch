{#
    True when a run label or run ID is one of the pipeline's own runs: Airflow's run IDs
    (scheduled__, asset_triggered__, manual__, backfill__), but not a drill (manual__drill-).
    dbt run from a laptop (run label "manual" or "manual-<time>") is not one.
#}

{% macro pipeline_run(column) -%}
    (regexp_like({{ column }}, '^(scheduled|asset_triggered|manual|backfill)__.*')
        and not startswith({{ column }}, 'manual__drill-'))
{%- endmacro %}
