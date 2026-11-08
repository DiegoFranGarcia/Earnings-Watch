-- One row per filing, with the company version it belongs to: the island of consecutive
-- filings with identical attributes. Gaps and islands: lag() flags each change, and a running
-- sum of the flags numbers the islands, so a company renamed A -> B -> A has three versions
-- (grouping by the attribute values instead would wrongly merge the two A periods).
-- Each filing keeps its own version, even when another filing accepted at the same instant
-- recorded different attributes: a time lookup could not tell those apart.
with filings as (
    select * from {{ ref('stg_sec__submissions') }}
),

with_previous as (
    -- Snowflake has no named WINDOW clause, so each lag() spells out the same ordering.
    select
        cik,
        accession_number,
        accepted_at,
        company_name,
        sic,
        incorporation_state,
        fiscal_year_end,
        filer_status,
        row_number() over (
            partition by cik order by accepted_at, accession_number
        ) as filing_sequence,
        lag(company_name) over (
            partition by cik order by accepted_at, accession_number
        ) as previous_company_name,
        lag(sic) over (
            partition by cik order by accepted_at, accession_number
        ) as previous_sic,
        lag(incorporation_state) over (
            partition by cik order by accepted_at, accession_number
        ) as previous_incorporation_state,
        lag(fiscal_year_end) over (
            partition by cik order by accepted_at, accession_number
        ) as previous_fiscal_year_end,
        lag(filer_status) over (
            partition by cik order by accepted_at, accession_number
        ) as previous_filer_status
    from filings
),

flagged as (
    select
        cik,
        accession_number,
        accepted_at,
        company_name,
        sic,
        incorporation_state,
        fiscal_year_end,
        filer_status,
        filing_sequence,
        -- The first filing always starts a version, even if every attribute is null.
        -- "is distinct from" treats null as a value: null -> 'DE' counts as a change.
        filing_sequence = 1
        or company_name is distinct from previous_company_name
        or sic is distinct from previous_sic
        or incorporation_state is distinct from previous_incorporation_state
        or fiscal_year_end is distinct from previous_fiscal_year_end
        or filer_status is distinct from previous_filer_status as starts_version
    from with_previous
),

numbered as (
    select
        cik,
        accession_number,
        accepted_at,
        company_name,
        sic,
        incorporation_state,
        fiscal_year_end,
        filer_status,
        filing_sequence,
        sum(iff(starts_version, 1, 0)) over (
            partition by cik
            order by accepted_at, accession_number
            rows between unbounded preceding and current row
        ) as version_number
    from flagged
)

select
    cik,
    accession_number,
    accepted_at,
    filing_sequence,
    company_name,
    sic,
    incorporation_state,
    fiscal_year_end,
    filer_status,
    version_number,
    md5(cik || '-' || version_number) as company_key
from numbered
