-- A span can be any length, but never negative. Any row returned is a failure.
select
    accession_number,
    tag,
    duration_quarters
from {{ ref('stg_sec__numbers') }}
where duration_quarters < 0
