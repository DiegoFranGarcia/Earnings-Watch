-- Our logic, so it fails (ADR 8). Deadlines on days EDGAR was closed, each announced by the
-- SEC as moving to the date given, and on weekends, must move there in int_sec_calendar.
with known (deadline, moves_to) as (
    select *
    from
        values
        ('2025-03-01'::date, '2025-03-03'::date),  -- a Saturday
        ('2025-01-09'::date, '2025-01-10'::date),  -- national day of mourning
        ('2024-12-24'::date, '2024-12-26'::date),  -- Christmas Eve, then Christmas Day
        ('2025-12-24'::date, '2025-12-29'::date),  -- closed December 24 to 26, then a weekend
        ('2021-06-18'::date, '2021-06-21'::date),  -- Juneteenth observed, then a weekend
        ('2018-12-05'::date, '2018-12-06'::date),  -- national day of mourning
        ('2014-12-26'::date, '2014-12-29'::date),  -- executive order, then a weekend
        ('2020-07-03'::date, '2020-07-06'::date),  -- Independence Day observed on Friday
        ('2025-03-31'::date, '2025-03-31'::date)   -- an ordinary Monday stays
)

select
    known.deadline,
    known.moves_to,
    calendar.next_business_day
from known
left join {{ ref('int_sec_calendar') }} as calendar
    on known.deadline = calendar.calendar_date
where calendar.next_business_day is distinct from known.moves_to
