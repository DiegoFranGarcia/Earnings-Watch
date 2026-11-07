-- A finding about filer data, not a pipeline bug, so it warns instead of failing.
-- Filings accepted at the same instant (EDGAR records acceptance to the minute) that record
-- different company attributes produce a zero-length version. Both records are kept: each
-- filing joins to its own version. Full history: 2, e.g. W. P. Carey's 8-K and 425 of
-- 2013-11-14 18:30 giving SIC 6500 and 6798.
{{ config(severity = 'warn') }}

select
    cik,
    version_number,
    company_name,
    valid_from,
    valid_to
from {{ ref('dim_company') }}
where valid_from = valid_to
