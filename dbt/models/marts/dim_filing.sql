-- One row per XBRL filing in the Financial Statement Data Sets, joined to the company version
-- the filing itself belongs to.
with filings as (
    select * from {{ ref('stg_sec__submissions') }}
),

versions as (
    select * from {{ ref('int_company__filing_versions') }}
)

select
    filings.accession_number,
    filings.cik,
    versions.company_key,
    filings.form,
    filings.filer_status,
    filings.fiscal_year,
    filings.fiscal_period,
    filings.period_end,
    filings.filed_date,
    filings.accepted_at,
    filings.was_later_amended,
    filings.co_registrant_count,
    filings.source_quarter,
    endswith(filings.form, '/A') as is_amendment,
    datediff(day, filings.period_end, filings.filed_date) as days_after_period_end
from filings
inner join versions
    on filings.accession_number = versions.accession_number
