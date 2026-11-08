-- One row per company, metric and period (value date and duration): every value ever
-- reported for it, in order of filing. The first-reported value is what was known when it
-- was first published (no look-ahead bias); the latest is today's best knowledge.
with facts as (
    select * from {{ ref('int_facts__canonical') }}
),

filings as (
    select * from {{ ref('stg_sec__submissions') }}
),

reports as (
    -- Inner join: numbers whose filing the SEC never listed cannot be ordered, so they drop.
    select
        facts.cik,
        facts.metric,
        facts.value_date,
        facts.duration_quarters,
        facts.value,
        facts.tag,
        facts.accession_number,
        facts.loaded_at,
        filings.accepted_at,
        filings.form,
        first_value(facts.value) over (
            partition by facts.cik, facts.metric, facts.value_date, facts.duration_quarters
            order by filings.accepted_at, facts.accession_number
        ) as first_fact_value,
        row_number() over (
            partition by facts.cik, facts.metric, facts.value_date, facts.duration_quarters
            order by filings.accepted_at, facts.accession_number
        ) as report_order,
        count(*) over (
            partition by facts.cik, facts.metric, facts.value_date, facts.duration_quarters
        ) as report_count
    from facts
    inner join filings
        on facts.accession_number = filings.accession_number
),

marked as (
    -- A report's order if its value differs materially from the first report's, else null.
    select
        reports.*,
        iff(
            abs(reports.value - reports.first_fact_value)
            > {{ var('restatement_threshold') }} * abs(reports.first_fact_value),
            reports.report_order,
            null
        ) as change_order
    from reports
),

summarised as (
    select
        cik,
        metric,
        value_date,
        duration_quarters,
        max(report_count) as report_count,
        count(distinct value) as distinct_value_count,
        max(iff(report_order = 1, value, null)) as first_reported_value,
        max(iff(report_order = 1, accession_number, null)) as first_reported_accession_number,
        max(iff(report_order = 1, accepted_at, null)) as first_reported_at,
        max(iff(report_order = report_count, value, null)) as latest_value,
        max(iff(report_order = report_count, accession_number, null))
            as latest_accession_number,
        max(iff(report_order = report_count, accepted_at, null)) as latest_reported_at,
        max(iff(report_order = 1, tag, null)) as first_reported_tag,
        max(iff(report_order = report_count, tag, null)) as latest_tag,
        -- The first report that materially changed the value: min_by skips null orders, so
        -- reports that merely repeated (or rounded) the first value are ignored.
        min_by(accession_number, change_order) as first_change_accession_number,
        min_by(form, change_order) as first_change_form,
        min_by(tag, change_order) as first_change_tag,
        min_by(accepted_at, change_order) as first_change_at,
        min_by(value, change_order) as first_changed_value,
        -- When any report of this fact last arrived: drives incremental rebuilds downstream.
        max(loaded_at) as last_loaded_at
    from marked
    group by cik, metric, value_date, duration_quarters
)

select
    cik,
    metric,
    value_date,
    duration_quarters,
    report_count,
    distinct_value_count,
    first_reported_value,
    first_reported_accession_number,
    first_reported_at,
    latest_value,
    latest_accession_number,
    latest_reported_at,
    last_loaded_at,
    first_reported_tag,
    latest_tag,
    first_change_accession_number,
    first_change_form,
    first_change_tag,
    first_change_at,
    first_changed_value,
    md5(cik || '|' || metric || '|' || value_date || '|' || duration_quarters) as fact_key,
    latest_value - first_reported_value as restatement_amount,
    -- Material change only: rounding between filings is not a restatement. A first value
    -- of zero makes any later non-zero value a restatement.
    abs(latest_value - first_reported_value)
    > {{ var('restatement_threshold') }} * abs(first_reported_value) as is_restated
from summarised
