-- One value per filing, metric, date and duration, using the best tag the filing reports.
with numbers as (
    select * from {{ ref('stg_sec__numbers') }}
),

tag_map as (
    select * from {{ ref('metric_tag_map') }}
),

eligible as (
    select
        numbers.accession_number,
        numbers.cik,
        tag_map.metric,
        tag_map.priority,
        numbers.tag,
        numbers.value_date,
        numbers.duration_quarters,
        numbers.value
    from numbers
    inner join tag_map
        on numbers.tag = tag_map.tag
    where
        numbers.value is not null          -- a nil fact is not a number: it must not outrank one
        and numbers.is_entity_total        -- no segment breakdowns: they would double count
        and not numbers.has_key_conflict   -- ambiguous rows never feed a metric
        and numbers.unit = 'USD'
        and numbers.taxonomy_version like 'us-gaap/%'   -- standard tags only
)

select
    accession_number,
    cik,
    metric,
    tag,
    value_date,
    duration_quarters,
    value
from eligible
qualify row_number() over (
    partition by accession_number, metric, value_date, duration_quarters
    order by priority
) = 1
