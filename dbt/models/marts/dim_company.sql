-- Type 2 company dimension: one row per company version, rebuilt from point-in-time filing
-- attributes, so history reaches back to 2009 rather than starting at deployment.
-- A version is valid from its first filing until the next version's first filing.
with versions as (
    select * from {{ ref('int_company__attribute_changes') }}
)

select
    cik,
    version_number,
    company_name,
    sic,
    incorporation_state,
    fiscal_year_end,
    filer_status,
    valid_from,
    first_accession_number,
    filing_count,
    md5(cik || '-' || version_number) as company_key,
    lead(valid_from) over (partition by cik order by version_number) as valid_to,
    lead(valid_from) over (partition by cik order by version_number) is null as is_current
from versions
