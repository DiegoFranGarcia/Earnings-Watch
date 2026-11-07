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
        facts.accession_number,
        filings.accepted_at,
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
        max(iff(report_order = report_count, accepted_at, null)) as latest_reported_at
    from reports
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
    md5(cik || '|' || metric || '|' || value_date || '|' || duration_quarters) as fact_key,
    latest_value - first_reported_value as restatement_amount,
    -- Material change only: rounding between filings is not a restatement. A first value
    -- of zero makes any later non-zero value a restatement.
    abs(latest_value - first_reported_value)
    > {{ var('restatement_threshold') }} * abs(first_reported_value) as is_restated
from summarised
