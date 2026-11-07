-- One row per filing. Renames only: no filters, no joins, no business logic.
with source as (
    select * from {{ source('raw', 'fsds_sub') }}
)

select
    adsh as accession_number,
    cik,
    name as company_name,
    sic,
    form,
    fy as fiscal_year,
    fp as fiscal_period,
    fye as fiscal_year_end,
    period as period_end,
    filed as filed_date,
    afs as filer_status,
    prevrpt as was_later_amended,
    _source_quarter as source_quarter
from source
