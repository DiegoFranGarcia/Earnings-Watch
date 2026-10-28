-- A report cannot cover a period that ends after the day it was filed.
-- Any row returned is a failure.
select
    accession_number,
    period_end,
    filed_date
from {{ ref('stg_sec__submissions') }}
where period_end > filed_date
