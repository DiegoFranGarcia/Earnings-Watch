-- Every export the public site reads has rows: an empty one fails the build, so the circuit
-- breaker holds the site at its last good data instead of publishing blank pages (ADR 10, 17).
with counts as (
    select
        'export_screener' as export_model,
        count(*) as row_count
    from {{ ref('export_screener') }}
    union all
    select
        'export_company_quarters' as export_model,
        count(*) as row_count
    from {{ ref('export_company_quarters') }}
    union all
    select
        'export_company_history' as export_model,
        count(*) as row_count
    from {{ ref('export_company_history') }}
    union all
    select
        'export_restatements_by_year' as export_model,
        count(*) as row_count
    from {{ ref('export_restatements_by_year') }}
    union all
    select
        'export_restatements_largest' as export_model,
        count(*) as row_count
    from {{ ref('export_restatements_largest') }}
    union all
    select
        'export_filing_timeliness' as export_model,
        count(*) as row_count
    from {{ ref('export_filing_timeliness') }}
    union all
    select
        'export_pipeline_health' as export_model,
        count(*) as row_count
    from {{ ref('export_pipeline_health') }}
)

select
    export_model,
    row_count
from counts
where row_count = 0
