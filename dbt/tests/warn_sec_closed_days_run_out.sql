-- A reminder, so it warns. sec_closed_days must reach every deadline: once today is within
-- 180 days of its last day, add the next year (scripts/make_sec_closed_days.py) before
-- deadlines past it make int_filings__timeliness's tests fail.
{{ config(severity = 'warn') }}

select max(closed_date) as last_closed_day
from {{ ref('sec_closed_days') }}
having dateadd(day, -180, date_from_parts(year(max(closed_date)), 12, 31)) <= current_date()
