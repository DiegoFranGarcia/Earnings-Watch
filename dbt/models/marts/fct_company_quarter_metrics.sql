-- One row per company, metric and quarter end, with first-reported and latest values.
--
-- Incremental by affected keys, not by a time window: a filing accepted this week can restate
-- a quarter from years ago, so "the last N days" would miss it. Each run finds every
-- (company, metric) with any number loaded since the last run and rebuilds that pair's whole
-- quarterly history. The key is the pair, not the single period, because a changed figure
-- also changes the next derived quarter (a new H1 changes Q2 = H1 - Q1 and Q3 = 9M - H1).
-- delete+insert removes the pair's old rows first, so quarters that vanish go too.
{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key=['cik', 'metric'],
        on_schema_change='fail'
    )
}}

with quarters as (
    select * from {{ ref('int_facts__discrete_quarters') }}
),

companies as (
    select * from {{ ref('dim_company') }}
)

select
    quarters.quarter_key,
    quarters.cik,
    -- The company version current when the quarter first became knowable.
    companies.company_key,
    quarters.metric,
    quarters.period_end,
    quarters.fiscal_year,
    quarters.fiscal_quarter,
    cast(quarters.first_reported_value as decimal(28, 4)) as first_reported_value,
    cast(quarters.latest_value as decimal(28, 4)) as latest_value,
    quarters.first_known_at,
    quarters.latest_known_at,
    quarters.is_derived,
    quarters.source_duration_quarters,
    quarters.is_restated,
    quarters.last_loaded_at,
    cast(quarters.latest_value - quarters.first_reported_value as decimal(28, 4))
        as restatement_amount
from quarters
left join companies
    on
        quarters.cik = companies.cik
        and quarters.first_known_at >= companies.valid_from
        and (quarters.first_known_at < companies.valid_to or companies.valid_to is null)
{% if is_incremental() %}
    -- Only the (company, metric) pairs with any number loaded since the last run.
    where (quarters.cik, quarters.metric) in (
        select
            changed.cik,
            changed.metric
        from quarters as changed
        where changed.last_loaded_at > (
            select max(existing.last_loaded_at) from {{ this }} as existing
        )
    )
{% endif %}
