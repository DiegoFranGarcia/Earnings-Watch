-- After collapsing repeated listings, each (filing, company) pair appears exactly once.
-- Any row returned is a failure of our deduplication, not of the source.
select
    accession_number,
    cik,
    count(*) as rows_for_pair
from {{ ref('int_filings__daily_index') }}
group by accession_number, cik
having count(*) > 1
