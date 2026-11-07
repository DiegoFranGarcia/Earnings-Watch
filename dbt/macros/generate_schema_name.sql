{#
    Build into the schemas Terraform created (STAGING, INTERMEDIATE, MARTS), the ones the
    TRANSFORMER role holds grants on, instead of dbt's default "<target schema>_<custom>".
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
