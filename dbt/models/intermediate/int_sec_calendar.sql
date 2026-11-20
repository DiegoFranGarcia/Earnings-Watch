-- Every date from the first to the last year sec_closed_days covers: whether EDGAR accepted
-- filings that day, and the first day on or after it that it did. A filing deadline is that
-- next business day (Exchange Act Rule 0-3: a last day on a Saturday, Sunday or holiday moves
-- to the first business day following). Dates whose next business day lies past the seed's
-- last year have none (null): int_filings__timeliness's tests fail if a deadline needs one.
with bounds as (
    select
        date_from_parts(year(min(closed_date)), 1, 1) as first_date,
        date_from_parts(year(max(closed_date)), 12, 31) as last_date
    from {{ ref('sec_closed_days') }}
),

numbered as (
    -- More numbers than days in the seed's span (generator needs a constant); trimmed below.
    select row_number() over (order by seq4()) - 1 as day_number
    from table(generator(rowcount => 20000))
),

days as (
    select dateadd(day, numbered.day_number, bounds.first_date) as calendar_date
    from numbered
    cross join bounds
    where numbered.day_number <= datediff(day, bounds.first_date, bounds.last_date)
),

flagged as (
    select
        days.calendar_date,
        dayofweekiso(days.calendar_date) < 6 and closed.closed_date is null as is_business_day
    from days
    left join {{ ref('sec_closed_days') }} as closed
        on days.calendar_date = closed.closed_date
)

select
    calendar_date,
    is_business_day,
    min(iff(is_business_day, calendar_date, null)) over (
        order by calendar_date
        rows between current row and unbounded following
    ) as next_business_day
from flagged
