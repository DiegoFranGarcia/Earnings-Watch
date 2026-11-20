-- The restatements page's table: material restatements of net income, revenue and operating
-- cash flow, likely scale errors left out. Two sets, each row once: the var
-- site_largest_restatements largest by the amount changed, and the var site_largest_amendments
-- largest amendments (corrections) by the change as a share of the company's total assets,
-- among changes of at least var site_amendment_min_change. The second set brings in smaller
-- companies' real corrections, which the dollar ranking never reaches; ranking against assets,
-- not the figure itself, keeps changes from a near-zero base from dominating. Part of the
-- site's export contract (ADR 17).
with restatements as (
    select * from {{ ref('mart_restatements') }}
    where
        not is_likely_scale_error
        and metric in ('net_income', 'revenue', 'operating_cash_flow')
),

-- Total assets at the restated period's end, after restatements.
assets as (
    select
        cik,
        period_end,
        latest_value as total_assets
    from {{ ref('fct_company_quarter_metrics') }}
    where metric = 'total_assets'
    qualify row_number() over (partition by cik, period_end order by latest_known_at desc) = 1
),

measured as (
    select
        restatements.*,
        assets.total_assets,
        iff(
            assets.total_assets > 0,
            abs(cast(restatements.restatement_amount as double))
            / cast(assets.total_assets as double),
            null
        ) as change_to_assets,
        coalesce(
            restatements.restatement_kind = 'correction'
            and abs(restatements.restatement_amount) >= {{ var('site_amendment_min_change') }}
            and assets.total_assets > 0,
            false
        ) as is_ranked_amendment
    from restatements
    left join assets
        on
            restatements.cik = assets.cik
            and restatements.period_end = assets.period_end
),

ranked as (
    select
        *,
        row_number() over (
            order by abs(restatement_amount) desc, restatement_key asc
        ) as amount_rank,
        row_number() over (
            partition by is_ranked_amendment order by change_to_assets desc, restatement_key asc
        ) as amendment_rank
    from measured
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
    restatement_pct,
    cast(total_assets as decimal(28, 4)) as total_assets,
    cast(change_to_assets as double) as change_to_assets,
    case
        when
            amount_rank <= {{ var('site_largest_restatements') }}
            and is_ranked_amendment
            and amendment_rank <= {{ var('site_largest_amendments') }}
            then 'both'
        when amount_rank <= {{ var('site_largest_restatements') }} then 'amount'
        else 'share_of_assets'
    end as selected_by
from ranked
where
    amount_rank <= {{ var('site_largest_restatements') }}
    or (is_ranked_amendment and amendment_rank <= {{ var('site_largest_amendments') }})
