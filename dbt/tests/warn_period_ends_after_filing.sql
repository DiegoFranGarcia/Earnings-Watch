-- A finding about filer data, not a pipeline bug, so it warns instead of failing.
-- A report cannot cover a period that ends after the day it was filed; any row returned is a
-- filer's typo. Full history: 27 of 440,233 filings, mostly a wrong year (a Q1 10-Q filed in
-- May with a period ending that December). They match no facts on period_end, so they never
-- reach the mart.
{{ config(severity = 'warn') }}

select
    accession_number,
    period_end,
    filed_date
from {{ ref('stg_sec__submissions') }}
where period_end > filed_date
