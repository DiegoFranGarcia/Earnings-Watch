-- Every company has exactly one current version. Any row returned is a failure.
select
    cik,
    count_if(is_current) as current_rows
from {{ ref('dim_company') }}
group by cik
having count_if(is_current) != 1
