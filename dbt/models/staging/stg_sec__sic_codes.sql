-- The SEC's SIC codes, each with a plain industry group from the office that reviews its
-- filings: "Office of" removed. A few codes name two offices ("Office of Trade & Services or
-- Office of Energy & Transportation"); each is placed in the first office named, so every
-- company belongs to exactly one group, and that group also exists on its own.
select
    sic,
    industry_title,
    office,
    trim(regexp_replace(split_part(office, ' or ', 1), '^Office of ', '')) as industry_group
from {{ ref('sic_codes') }}
