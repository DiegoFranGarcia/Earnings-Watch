-- A finding about filer data, so it warns instead of failing. A restated value that is about
-- 1,000x (or 1/1,000x) the first-reported one is almost always a units mistake in the tagging,
-- e.g. Day One Biopharmaceuticals' net income: -$107.3m first, -$107,322m in a 10-K/A.
{{ config(severity = 'warn', store_failures = true) }}

select
    cik,
    company_name,
    metric,
    period_end,
    first_reported_value,
    latest_value,
    first_change_form
from {{ ref('mart_restatements') }}
where is_likely_scale_error
