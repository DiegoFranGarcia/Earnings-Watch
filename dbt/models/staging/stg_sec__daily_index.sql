-- One row per filing and company in EDGAR's daily index: every form, not only financial
-- statements (including late-filing notices such as NT 10-K). Renames only.
with source as (
    select * from {{ source('raw', 'daily_index') }}
)

select
    accession_number,
    cik,
    company_name,
    form_type as form,
    date_filed as filed_date,
    filename as file_name,
    _source_date as index_date,
    _loaded_at as loaded_at
from source
