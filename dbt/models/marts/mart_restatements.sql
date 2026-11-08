-- One row per materially restated fact (company, metric and period): what was first reported,
-- what it became, when the change first arrived, and what kind of change it was. Classified
-- by the first report that materially changed the value, checked in this order:
--   tag_switch: that report used a different XBRL tag (a different measure, not a restatement)
--   correction: that report was an amendment (10-K/A, 10-Q/A): the filer fixed a filed report
--   recast:     a later original filing's comparative columns re-presented it (discontinued
--               operations, reclassifications)
with versions as (
    select * from {{ ref('int_facts__versions') }}
    where is_restated
),

filing_versions as (
    select * from {{ ref('int_company__filing_versions') }}
),

companies as (
    select * from {{ ref('dim_company') }}
)

select
    versions.cik,
    -- The company version of the filing that made the change.
    filing_versions.company_key,
    companies.company_name,
    companies.sic,
    versions.metric,
    versions.value_date as period_end,
    versions.duration_quarters,
    versions.report_count,
    versions.first_reported_at,
    versions.first_reported_accession_number,
    versions.first_reported_tag,
    versions.first_change_at,
    versions.first_change_accession_number,
    versions.first_change_form,
    versions.first_change_tag,
    cast(versions.first_reported_value as decimal(28, 4)) as first_reported_value,
    cast(versions.first_changed_value as decimal(28, 4)) as first_changed_value,
    cast(versions.latest_value as decimal(28, 4)) as latest_value,
    cast(versions.restatement_amount as decimal(30, 4)) as restatement_amount,
    cast(
        versions.restatement_amount / nullif(abs(versions.first_reported_value), 0) as double
    ) as restatement_pct,
    md5(
        versions.cik || '|' || versions.metric || '|' || versions.value_date
        || '|' || versions.duration_quarters
    ) as restatement_key,
    datediff(day, versions.first_reported_at, versions.first_change_at) as days_to_first_change,
    -- A change of about 1,000x (or 1/1,000x) is almost always a units mistake in the tagging
    -- (thousands tagged as dollars), not a real restatement.
    -- Divided as doubles with nullif: SQL does not promise to evaluate "x != 0 and y / x" left
    -- to right, so a zero check cannot guard a division, and decimals could overflow.
    coalesce(
        abs(
            cast(versions.latest_value as double)
            / nullif(cast(versions.first_reported_value as double), 0)
        ) between 900 and 1100
        or abs(
            cast(versions.first_reported_value as double)
            / nullif(cast(versions.latest_value as double), 0)
        ) between 900 and 1100,
        false
    ) as is_likely_scale_error,
    case
        when versions.first_change_tag is distinct from versions.first_reported_tag
            then 'tag_switch'
        when endswith(versions.first_change_form, '/A') then 'correction'
        else 'recast'
    end as restatement_kind
from versions
left join filing_versions
    on versions.first_change_accession_number = filing_versions.accession_number
left join companies
    on filing_versions.company_key = companies.company_key
