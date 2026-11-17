-- A deliberately broken model, to prove slim CI fails on it. Never merged.
select no_such_column from {{ ref('mart_filing_timeliness') }}
