-- One row per number reported in a filing, exactly as filed: every version of every fact is
-- kept, joined to the company version its filing belongs to, and labelled with a canonical
-- metric where its tag maps to one.
--
-- Incremental by source quarter: a reloaded quarter's rows are deleted and reinserted as a
-- block, so a republished quarter replaces cleanly. Nothing here is derived across quarters,
-- so the quarter is a correct key (unlike the company-quarter fact).
{{
    config(
        materialized='incremental',
        incremental_strategy='delete+insert',
        unique_key='source_quarter',
        on_schema_change='fail'
    )
}}

with numbers as (
    select * from {{ ref('stg_sec__numbers') }}
),

versions as (
    select * from {{ ref('int_company__filing_versions') }}
),

tag_map as (
    select * from {{ ref('metric_tag_map') }}
)

select
    numbers.accession_number,
    numbers.cik,
    -- Null only for the numbers whose filing the SEC never listed (2013q1).
    versions.company_key,
    tag_map.metric,
    numbers.tag,
    numbers.taxonomy_version,
    numbers.value_date,
    numbers.duration_quarters,
    numbers.unit,
    numbers.segments,
    numbers.co_registrant,
    cast(numbers.value as decimal(28, 4)) as reported_value,
    numbers.footnote,
    numbers.is_entity_total,
    numbers.period_type,
    numbers.has_key_conflict,
    numbers.source_quarter,
    numbers.loaded_at,
    -- The SEC's eight-column key is not unique here (conflicting values share it), so the
    -- value and footnote are part of the key: exactly Spark's exact-duplicate rule.
    -- concat_ws returns null if any part is null, so nullable parts are coalesced.
    md5(concat_ws(
        '|',
        numbers.accession_number,
        numbers.tag,
        numbers.taxonomy_version,
        numbers.value_date,
        numbers.duration_quarters,
        numbers.unit,
        coalesce(numbers.segments, ''),
        coalesce(numbers.co_registrant, ''),
        coalesce(to_varchar(numbers.value), 'nil'),
        coalesce(numbers.footnote, '')
    )) as reported_fact_key
from numbers
left join versions
    on numbers.accession_number = versions.accession_number
left join tag_map
    on
        numbers.tag = tag_map.tag
        and numbers.taxonomy_version like 'us-gaap/%'
{% if is_incremental() %}
    -- Only the source quarters with any number loaded since the last run.
    where numbers.source_quarter in (
        select changed.source_quarter
        from numbers as changed
        where changed.loaded_at > (
            select max(existing.loaded_at) from {{ this }} as existing
        )
    )
{% endif %}
