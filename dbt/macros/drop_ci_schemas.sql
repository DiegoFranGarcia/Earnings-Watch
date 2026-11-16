{#
    Drop one pull request's schemas from the CI database, when the pull request closes:
        dbt run-operation drop_ci_schemas --target ci --args '{prefix: PR_12}'
    Matches the prefix exactly, in code: a SQL pattern such as LIKE 'PR_12_%' would also match
    PR_123_STAGING, because "_" matches any character. Runs only against the ci target and the
    EARNINGSWATCH_CI database, and drops only schemas this role can see there.
#}
{% macro drop_ci_schemas(prefix) %}
    {% if target.name != 'ci' or target.database | upper != 'EARNINGSWATCH_CI' %}
        {% set message = "drop_ci_schemas runs only against the ci target, in EARNINGSWATCH_CI" %}
        {{ exceptions.raise_compiler_error(message) }}
    {% endif %}
    {% set prefix = prefix | string | trim | upper %}
    {% if not modules.re.fullmatch("PR_[0-9]+", prefix) %}
        {% set message = "drop_ci_schemas expects a prefix like PR_12, got: " ~ prefix %}
        {{ exceptions.raise_compiler_error(message) }}
    {% endif %}
    {% set schemas = run_query("show terse schemas in database " ~ target.database) %}
    {% set dropped = [] %}
    {% for row in schemas %}
        {% set name = row["name"] | upper %}
        {% if name.startswith(prefix ~ "_") %}
            {% do run_query("drop schema if exists " ~ target.database ~ "." ~ name) %}
            {% do dropped.append(name) %}
        {% endif %}
    {% endfor %}
    {% set summary = (dropped | length) ~ " schema(s) for " ~ prefix %}
    {{ log("dropped " ~ summary ~ ": " ~ (dropped | join(", ")), info=True) }}
{% endmacro %}
