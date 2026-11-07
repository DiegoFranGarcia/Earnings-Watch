-- One row per filing. Renames and types only: no filters, no joins, no business logic.
-- Company attributes are as recorded on this filing, which makes history reconstructable.
with source as (
    select * from {{ source('raw', 'fsds_sub') }}
)

select
    adsh as accession_number,
    cik,
    name as company_name,
    former as former_company_name,
    changed as name_changed_date,
    sic,
    countryba as business_country,
    stprba as business_state,
    cityba as business_city,
    zipba as business_zip,
    bas1 as business_address_1,
    bas2 as business_address_2,
    baph as business_phone,
    countryma as mailing_country,
    stprma as mailing_state,
    cityma as mailing_city,
    zipma as mailing_zip,
    mas1 as mailing_address_1,
    mas2 as mailing_address_2,
    countryinc as incorporation_country,
    stprinc as incorporation_state,
    ein as employer_id_number,
    afs as filer_status,
    wksi as is_well_known_seasoned_issuer,
    fye as fiscal_year_end,
    form,
    period as period_end,
    fy as fiscal_year,
    fp as fiscal_period,
    filed as filed_date,
    accepted as accepted_at,
    prevrpt as was_later_amended,
    detail as has_detailed_tagging,
    instance as instance_file,
    nciks as co_registrant_count,
    aciks as additional_ciks,
    _source_quarter as source_quarter,
    _loaded_at as loaded_at
from source
