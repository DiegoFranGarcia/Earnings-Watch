-- The filing-timeliness page: original 10-Ks and 10-Qs by filer group, form and period year.
-- Groups, not statuses: the SEC re-coded statuses in 2018 and 2020, and each group shares one
-- deadline (assert_filer_groups_share_a_deadline). Computed from the filings, not from
-- mart_filing_timeliness, so each group's medians are its own, not combined from its
-- statuses'. Part of the site's export contract (ADR 17).
with filings as (
    select
        *,
        year(period_end) as period_year
    from {{ ref('int_filings__timeliness') }}
),

grouped as (
    select
        filer_group,
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
        min(notice_data_available) as notice_data_available,
        any_value(deadline_days) as deadline_days,
        any_value(extension_days) as extension_days
    from filings
    group by filer_group, form, period_year
)

select
    filer_group,
    form,
    period_year,
    filings,
    on_time_filings,
    within_extension_filings,
    late_filings,
    late_notices,
    notice_data_available,
    deadline_days,
    extension_days,
    cast(median_days_to_file as decimal(10, 1)) as median_days_to_file,
    cast(p90_days_to_file as decimal(10, 1)) as p90_days_to_file,
    cast(median_days_past_due_when_late as decimal(10, 1)) as median_days_past_due_when_late,
    cast(on_time_filings / filings as double) as on_time_share,
    md5(filer_group || '|' || form || '|' || period_year) as timeliness_key
from grouped
