-- The site draws each company at (change in net income / assets, gap / assets) and highlights
-- the flagged ones, so a flagged company must sit right of zero and above the threshold: its
-- net income rose (the flag's own test), and its gap is above var accrual_ratio_threshold.
select
    cik,
    reporting_view
from {{ ref('export_screener') }}
where
    is_flagged
    and not (
        ttm_net_income > prior_ttm_net_income
        and accruals_to_assets > {{ var('accrual_ratio_threshold') }}
    )
