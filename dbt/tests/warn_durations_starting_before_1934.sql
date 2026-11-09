-- A finding about filer data, not a pipeline bug, so it warns instead of failing.
-- The SEC was created in 1934; no filing can cover a period that starts before then,
-- so such a span is a filer's typo (2026q3 holds one of 7,288 quarters: 1,822 years).
{{ config(severity = 'warn', store_failures = true) }}

select
    accession_number,
    tag,
    value_date,
    duration_quarters
from {{ ref('stg_sec__numbers') }}
where extract(year from value_date) - duration_quarters / 4.0 < 1934
