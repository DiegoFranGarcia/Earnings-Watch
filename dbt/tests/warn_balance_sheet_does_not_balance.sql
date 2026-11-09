-- A finding about filer data, so it warns instead of failing. Total assets must equal total
-- liabilities and stockholders' equity; any quarter-end where they differ by more than
-- var restatement_threshold is a tagging error in the filing (latest values).
{{ config(severity = 'warn', store_failures = true) }}

with balances as (
    select
        cik,
        period_end,
        max(iff(metric = 'total_assets', latest_value, null)) as total_assets,
        max(iff(metric = 'liabilities_and_equity', latest_value, null)) as liabilities_and_equity
    from {{ ref('fct_company_quarter_metrics') }}
    where metric in ('total_assets', 'liabilities_and_equity')
    group by cik, period_end
)

select
    cik,
    period_end,
    total_assets,
    liabilities_and_equity
from balances
where
    total_assets is not null
    and liabilities_and_equity is not null
    and abs(total_assets - liabilities_and_equity)
    > {{ var('restatement_threshold') }} * abs(total_assets)
