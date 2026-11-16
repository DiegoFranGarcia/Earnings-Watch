{#
    Build into the schemas Terraform created (STAGING, INTERMEDIATE, MARTS), the ones the
    TRANSFORMER role holds grants on, instead of dbt's default "<target schema>_<custom>".

    The ci target (pull requests) is the exception: each pull request builds into schemas of its
    own, prefixed with the target schema (PR_12_STAGING, PR_12_MARTS), so pull requests running at
    the same time never touch each other's models.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.name == 'ci' -%}
        {{ target.schema | trim | upper }}_{{ custom_schema_name | trim | upper }}
    {%- else -%}
        {{ custom_schema_name | trim | upper }}
    {%- endif -%}
{%- endmacro %}
