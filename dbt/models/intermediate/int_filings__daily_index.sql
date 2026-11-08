-- One row per filing and company in EDGAR's daily index: each pair's first appearance, the
-- day it became public. The index repeats some pairs (identical lines for multi-series fund
-- filings, or a listing on a second day); how often and until when is kept, not hidden.
with listings as (
    select * from {{ ref('stg_sec__daily_index') }}
)

select
    accession_number,
    cik,
    company_name,
    form,
    filed_date,
    file_name,
    index_date as first_index_date,
    count(*) over (partition by accession_number, cik) as listing_count,
    max(index_date) over (partition by accession_number, cik) as last_index_date
from listings
qualify row_number() over (
    partition by accession_number, cik
    order by index_date, form, company_name
) = 1
