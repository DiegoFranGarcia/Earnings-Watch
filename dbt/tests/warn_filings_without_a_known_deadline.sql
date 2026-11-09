-- A finding about filer data, so it warns instead of failing. Original 10-Ks and 10-Qs whose
-- recorded filer status has no deadline in filing_deadlines (missing or unknown) cannot be
-- measured for timeliness and are left out of int_filings__timeliness; this counts them.
{{ config(severity = 'warn', store_failures = true) }}

select
    filings.accession_number,
    filings.form,
    filings.filer_status
from {{ ref('dim_filing') }} as filings
left join {{ ref('filing_deadlines') }} as deadlines
    on
        filings.filer_status = deadlines.filer_status
        and filings.form = deadlines.form
where
    filings.form in ('10-K', '10-Q')
    and deadlines.filer_status is null
