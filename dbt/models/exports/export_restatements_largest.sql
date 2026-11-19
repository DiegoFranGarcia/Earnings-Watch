-- The restatements page's table: the largest material restatements of net income, revenue and
-- operating cash flow, by the absolute amount changed. Likely scale errors are left out. Part
-- of the site's export contract (ADR 17); var site_largest_restatements sets how many.
with restatements as (
    select * from {{ ref('mart_restatements') }}
    where
        not is_likely_scale_error
        and metric in ('net_income', 'revenue', 'operating_cash_flow')
)

select
    restatement_key,
    cik,
    company_name,
    metric,
    period_end,
    duration_quarters,
    restatement_kind,
    first_change_form,
    first_reported_at,
    first_change_at,
    days_to_first_change,
    first_reported_value,
    latest_value,
    restatement_amount,
    restatement_pct
from restatements
qualify
    row_number() over (order by abs(restatement_amount) desc, restatement_key)
    <= {{ var('site_largest_restatements') }}
