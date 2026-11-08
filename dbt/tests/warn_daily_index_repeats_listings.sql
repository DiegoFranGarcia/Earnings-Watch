-- A finding about the source, so it warns instead of failing. EDGAR's daily index repeats
-- some (filing, company) pairs: 25,661 in 2025-2026. 94% are identical lines, mostly fund and
-- asset-backed filings covering many series (one listing per series, but the file carries no
-- series identifier); 1,453 appear on two different days. int_filings__daily_index keeps
-- each pair's first appearance.
{{ config(severity = 'warn') }}

select
    accession_number,
    cik,
    count(*) as listings
from {{ ref('stg_sec__daily_index') }}
group by accession_number, cik
having count(*) > 1
