{#
    on-run-end: record every model, seed and test result of this dbt invocation in
    AUDIT.DBT_RESULTS. Cosmos runs dbt once per Airflow task, so each task records its own
    results, tagged with the Airflow run that started it (DBT_RUN_LABEL).
#}

{% macro sql_string(value) -%}
    {#- A Snowflake string literal: quotes and backslashes escaped, so a message containing
        an apostrophe can neither break the insert nor change it. -#}
    {%- if value is none -%}
        null
    {%- else -%}
        '{{ (value | string) | replace("\\", "\\\\") | replace("'", "''") }}'
    {%- endif -%}
{%- endmacro %}

{% macro sql_number(value) -%}
    {%- if value is none -%}null{%- else -%}{{ value }}{%- endif -%}
{%- endmacro %}

{% macro log_dbt_results(results) %}
    {% if execute and results %}
        {% set audit_table = target.database ~ ".AUDIT.DBT_RESULTS" %}
        {% do run_query(
            "create table if not exists " ~ audit_table ~ " ("
            ~ "invocation_id varchar, run_label varchar, run_started_at timestamp_ntz, "
            ~ "unique_id varchar, resource_type varchar, node_name varchar, status varchar, "
            ~ "failures number, rows_affected number, execution_seconds float, "
            ~ "message varchar, recorded_at timestamp_ntz)"
        ) %}
        {% set rows = [] %}
        {% for result in results %}
            {% set response = result.adapter_response or {} %}
            {% do rows.append(
                "("
                ~ sql_string(invocation_id) ~ ", "
                ~ sql_string(env_var("DBT_RUN_LABEL", "manual")) ~ ", "
                ~ sql_string(run_started_at.strftime("%Y-%m-%d %H:%M:%S")) ~ "::timestamp_ntz, "
                ~ sql_string(result.node.unique_id) ~ ", "
                ~ sql_string(result.node.resource_type) ~ ", "
                ~ sql_string(result.node.name) ~ ", "
                ~ sql_string(result.status) ~ ", "
                ~ sql_number(result.failures) ~ ", "
                ~ sql_number(response.get("rows_affected")) ~ ", "
                ~ sql_number(result.execution_time) ~ ", "
                ~ sql_string((result.message or "")[:1000]) ~ ", "
                ~ "sysdate())"
            ) %}
        {% endfor %}
        {% do run_query("insert into " ~ audit_table ~ " values " ~ rows | join(", ")) %}
    {% endif %}
{% endmacro %}
