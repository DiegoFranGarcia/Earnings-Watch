-- One row per filer status, form and period year: how many 10-K or 10-Q filings were on time,
-- within a late-filing notice's extension, or late, and how long filers took. Notices are
-- known only from 2025 (notice_data_available), so earlier years count extensions as late.
with filings as (
    select
        *,
        year(period_end) as period_year
    from {{ ref('int_filings__timeliness') }}
),

grouped as (
    select
        filer_status,
        form,
        period_year,
        count(*) as filings,
        count_if(timeliness = 'on_time') as on_time_filings,
        count_if(timeliness = 'within_extension') as within_extension_filings,
        count_if(timeliness = 'late') as late_filings,
        count_if(filed_late_notice) as late_notices,
        median(days_after_period_end) as median_days_to_file,
        percentile_cont(0.9) within group (order by days_after_period_end)
            as p90_days_to_file,
        median(iff(timeliness != 'on_time', days_past_due, null))
            as median_days_past_due_when_late,
        -- True when every filing in the group falls in the daily index's coverage.
        min(notice_data_available) as notice_data_available
    from filings
    group by filer_status, form, period_year
)

select
    filer_status,
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
    cast(on_time_filings / filings as double) as on_time_share,
    md5(filer_status || '|' || form || '|' || period_year) as timeliness_key
from grouped
