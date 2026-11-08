-- One row per original 10-K or 10-Q: its deadline (by the filer status recorded on the
-- filing), whether it was filed on time, and any late-filing notice (NT 10-K / NT 10-Q).
-- A deadline on a weekend moves to the next Monday; federal holidays are not modelled.
-- Notices come from the daily index, which starts on 2025-01-02, so earlier filings that
-- used an extension can only show as late (notice_data_available says which is which).
with filings as (
    select * from {{ ref('dim_filing') }}
    where
        form in ('10-K', '10-Q')
        and period_end is not null
        and filed_date >= period_end
),

deadlines as (
    select * from {{ ref('filing_deadlines') }}
),

notices as (
    select
        cik,
        form as notice_form,
        filed_date as notice_date,
        accession_number as notice_accession_number
    from {{ ref('int_filings__daily_index') }}
    where form in ('NT 10-K', 'NT 10-Q')
),

scheduled as (
    select
        filings.accession_number,
        filings.cik,
        filings.company_key,
        filings.form,
        filings.filer_status,
        filings.period_end,
        filings.filed_date,
        deadlines.deadline_days,
        deadlines.extension_days,
        deadlines.filer_group,
        dateadd(day, deadlines.deadline_days, filings.period_end) as statutory_date
    from filings
    inner join deadlines
        on
            filings.filer_status = deadlines.filer_status
            and filings.form = deadlines.form
),

due as (
    select
        scheduled.*,
        -- A deadline on Saturday or Sunday moves to the following Monday.
        case dayofweekiso(scheduled.statutory_date)
            when 6 then dateadd(day, 2, scheduled.statutory_date)
            when 7 then dateadd(day, 1, scheduled.statutory_date)
            else scheduled.statutory_date
        end as due_date
    from scheduled
),

with_notice as (
    -- The earliest matching notice filed after the period ended and no later than a few
    -- days after the deadline (the rule allows one business day; five allows a weekend).
    select
        due.*,
        notices.notice_accession_number,
        notices.notice_date
    from due
    left join notices
        on
            due.cik = notices.cik
            and 'NT ' || due.form = notices.notice_form
            and notices.notice_date between due.period_end and dateadd(day, 5, due.due_date)
    qualify row_number() over (
        partition by due.accession_number
        order by notices.notice_date
    ) = 1
)

select
    accession_number,
    cik,
    company_key,
    form,
    filer_status,
    filer_group,
    period_end,
    filed_date,
    deadline_days,
    extension_days,
    due_date,
    notice_accession_number,
    notice_date,
    datediff(day, period_end, filed_date) as days_after_period_end,
    datediff(day, due_date, filed_date) as days_past_due,
    notice_accession_number is not null as filed_late_notice,
    filed_date >= '2025-01-02'::date as notice_data_available,
    case
        when filed_date <= due_date then 'on_time'
        when
            notice_accession_number is not null
            and filed_date <= dateadd(day, extension_days, due_date)
            then 'within_extension'
        else 'late'
    end as timeliness
from with_notice
