-- The canonical model promises one value per filing, metric, date and duration.
select
    accession_number,
    metric,
    value_date,
    duration_quarters,
    count(*) as copies
from {{ ref('int_facts__canonical') }}
group by accession_number, metric, value_date, duration_quarters
having count(*) > 1
