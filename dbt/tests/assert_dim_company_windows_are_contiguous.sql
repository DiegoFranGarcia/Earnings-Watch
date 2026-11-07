-- Each version must end exactly where the next begins: no gaps, no overlaps, and no window
-- that runs backwards. A zero-length window (valid_from = valid_to) is allowed: it happens
-- when filings accepted at the same instant record different attributes, and is reported by
-- warn_simultaneous_filings_disagree. Any row returned is a failure.
with versions as (
    select
        cik,
        version_number,
        valid_from,
        valid_to,
        lead(valid_from) over (partition by cik order by version_number) as next_valid_from
    from {{ ref('dim_company') }}
)

select
    cik,
    version_number,
    valid_from,
    valid_to,
    next_valid_from
from versions
where
    valid_to is distinct from next_valid_from
    or valid_from > valid_to
