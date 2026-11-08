-- One row per company version: the filings of int_company__filing_versions grouped by the
-- island they belong to. Every filing in a version has the same attributes, so any_value is
-- exact here.
with filings as (
    select * from {{ ref('int_company__filing_versions') }}
)

select
    cik,
    version_number,
    any_value(company_name) as company_name,
    any_value(sic) as sic,
    any_value(incorporation_state) as incorporation_state,
    any_value(fiscal_year_end) as fiscal_year_end,
    any_value(filer_status) as filer_status,
    min(accepted_at) as valid_from,
    -- filing_sequence breaks ties between filings accepted at the same instant.
    min_by(accession_number, filing_sequence) as first_accession_number,
    count(*) as filing_count
from filings
group by cik, version_number
