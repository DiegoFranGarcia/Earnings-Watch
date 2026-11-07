-- One row per number reported in a filing. Renames only: no filters, no joins, no logic.
with source as (
    select * from {{ source('raw', 'fsds_num') }}
)

select
    adsh as accession_number,
    cik,
    tag,
    version as taxonomy_version,
    ddate as value_date,
    qtrs as duration_quarters,
    uom as unit,
    segments,
    coreg as co_registrant,
    value,
    footnote,
    form,
    filed as filed_date,
    fy as fiscal_year,
    fp as fiscal_period,
    is_entity_total,
    period_type,
    has_key_conflict,
    _source_quarter as source_quarter,
    _loaded_at as loaded_at
from source
