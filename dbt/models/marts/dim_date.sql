-- A plain calendar, one row per day from 2000 through 2035. Fiscal labels stay on the facts,
-- because every company's fiscal calendar differs; this table is shared by all of them.
with days as (
    -- seq4() may skip numbers, so row_number() over it gives a gap-free day offset.
    select dateadd(day, row_number() over (order by seq4()) - 1, '2000-01-01'::date) as date_day
    from table(generator(rowcount => 13149))
)

select
    date_day,
    year(date_day) as calendar_year,
    quarter(date_day) as calendar_quarter,
    month(date_day) as calendar_month,
    dayofweekiso(date_day) as iso_day_of_week,
    last_day(date_day) = date_day as is_month_end,
    last_day(date_day, quarter) = date_day as is_quarter_end,
    last_day(date_day, year) = date_day as is_year_end
from days
