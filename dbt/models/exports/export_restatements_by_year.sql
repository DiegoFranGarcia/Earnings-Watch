-- The restatements page's summary: material restatements by the year they first appeared, how
-- they arose and which metric they changed. Likely scale errors (a units mistake, about 1,000x)
-- are left out, as mart_restatements advises. Part of the site's export contract (ADR 17).
with restatements as (
    select * from {{ ref('mart_restatements') }}
    where not is_likely_scale_error
),

grouped as (
    select
        restatement_kind,
        metric,
        year(first_change_at) as change_year,
        count(*) as restatements,
        count(distinct cik) as companies,
        median(abs(restatement_pct)) as median_abs_restatement_pct,
        median(days_to_first_change) as median_days_to_first_change
    from restatements
    group by restatement_kind, metric, year(first_change_at)
)

select
    change_year,
    restatement_kind,
    metric,
    restatements,
    companies,
    median_abs_restatement_pct,
    median_days_to_first_change,
    md5(change_year || '|' || restatement_kind || '|' || metric) as restatement_group_key
from grouped
