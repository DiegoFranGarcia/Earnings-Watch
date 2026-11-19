-- The filing-timeliness page: the whole mart, which is small (one row per filer status, form
-- and period year). Part of the site's export contract (ADR 17).
select
    timeliness_key,
    filer_status,
    filer_group,
    form,
    period_year,
    filings,
    on_time_filings,
    within_extension_filings,
    late_filings,
    late_notices,
    median_days_to_file,
    p90_days_to_file,
    median_days_past_due_when_late,
    notice_data_available,
    on_time_share
from {{ ref('mart_filing_timeliness') }}
