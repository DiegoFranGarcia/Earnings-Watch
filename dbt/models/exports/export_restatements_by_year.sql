-- The restatements page's summary: material restatements by the year they first appeared, how
-- they arose and which metric they changed, and the companies that reported that metric that
-- year (the rate's denominator). Likely scale errors (a units mistake, about 1,000x) are left
-- out, as mart_restatements advises. Part of the site's export contract (ADR 17).
with restatements as (
    select
        *,
        year(first_change_at) as change_year
    from {{ ref('mart_restatements') }}
    where not is_likely_scale_error
),

grouped as (
    select
        restatement_kind,
        metric,
        change_year,
        count(*) as restatements,
        count(distinct cik) as companies,
        median(abs(restatement_pct)) as median_abs_restatement_pct,
        median(days_to_first_change) as median_days_to_first_change
    from restatements
    group by restatement_kind, metric, change_year
),

-- Each company once per year and metric, under its first kind in this order: an amendment
-- (correction), a later filing (recast), a tag switch. These counts stack: together they are
-- the companies that changed the metric that year, and leaving tag switches out leaves the rest.
company_ranks as (
    select
        cik,
        metric,
        change_year,
        min(case restatement_kind when 'correction' then 1 when 'recast' then 2 else 3 end)
            as kind_rank
    from restatements
    group by cik, metric, change_year
),

companies_by_first_kind as (
    select
        metric,
        change_year,
        case kind_rank when 1 then 'correction' when 2 then 'recast' else 'tag_switch' end
            as restatement_kind,
        count(*) as companies_by_first_kind
    from company_ranks
    group by metric, change_year, kind_rank
),

-- The rate's denominator, from the same facts the restatements come from: companies whose 10-K
-- or 10-Q filings that year (amendments included) report the metric in a form the models read
-- (a standard US-GAAP tag, in USD, for the whole entity; int_facts__canonical's rules).
reporting as (
    select
        reported.metric,
        year(filed.accepted_at) as change_year,
        count(distinct reported.cik) as reporting_companies
    from {{ ref('fct_reported_facts') }} as reported
    inner join {{ ref('dim_filing') }} as filed
        on reported.accession_number = filed.accession_number
    where
        reported.reported_value is not null
        and reported.is_entity_total
        and not reported.has_key_conflict
        and reported.unit = 'USD'
        and reported.taxonomy_version like 'us-gaap/%'
        and filed.form in ('10-K', '10-Q', '10-K/A', '10-Q/A')
    group by reported.metric, year(filed.accepted_at)
)

select
    grouped.change_year,
    grouped.restatement_kind,
    grouped.metric,
    grouped.restatements,
    grouped.companies,
    reporting.reporting_companies,
    grouped.median_abs_restatement_pct,
    grouped.median_days_to_first_change,
    coalesce(companies_by_first_kind.companies_by_first_kind, 0) as companies_by_first_kind,
    md5(grouped.change_year || '|' || grouped.restatement_kind || '|' || grouped.metric)
        as restatement_group_key
from grouped
left join companies_by_first_kind
    on
        grouped.metric = companies_by_first_kind.metric
        and grouped.change_year = companies_by_first_kind.change_year
        and grouped.restatement_kind = companies_by_first_kind.restatement_kind
left join reporting
    on
        grouped.metric = reporting.metric
        and grouped.change_year = reporting.change_year
