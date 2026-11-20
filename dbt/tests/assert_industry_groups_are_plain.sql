-- Every industry group is one plain name: no "Office of", and no "or" joining two offices.
select
    sic,
    office,
    industry_group
from {{ ref('stg_sec__sic_codes') }}
where
    industry_group ilike '%office of%'
    or industry_group ilike '% or %'
    or industry_group = ''
