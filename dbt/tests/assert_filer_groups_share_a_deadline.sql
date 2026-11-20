-- Our logic, so it fails (ADR 8). The site reports timeliness by filer group, with one
-- deadline and one extension per group and form: every status in a group must share them.
select
    filer_group,
    form,
    count(distinct deadline_days) as deadlines,
    count(distinct extension_days) as extensions
from {{ ref('filing_deadlines') }}
group by filer_group, form
having count(distinct deadline_days) > 1 or count(distinct extension_days) > 1
