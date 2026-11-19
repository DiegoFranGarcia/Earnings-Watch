-- The company page's history: every version of each screener company (its names, industries
-- and filer statuses over time, and when each began). One row per company version. Part of the
-- site's export contract (ADR 17).
with screener_companies as (
    select distinct cik from {{ ref('export_screener') }}
),

versions as (
    select * from {{ ref('dim_company') }}
    where cik in (select screener_companies.cik from screener_companies)
),

industries as (
    select * from {{ ref('sic_codes') }}
)

select
    versions.company_key,
    versions.cik,
    versions.version_number,
    versions.company_name,
    versions.sic,
    industries.industry_title,
    versions.filer_status,
    versions.valid_from,
    versions.valid_to,
    versions.is_current
from versions
left join industries on versions.sic = industries.sic
