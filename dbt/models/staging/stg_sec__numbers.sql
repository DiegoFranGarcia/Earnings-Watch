-- One row per number reported in a filing. Renames only.
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
    value,
    is_entity_total,
    has_key_conflict,
    _source_quarter as source_quarter
from source
