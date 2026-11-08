# 4. Run dbt on Snowflake; retire the DuckDB target

## Context
The slice built dbt on DuckDB, reading silver Parquet directly. Snowflake's RAW now holds the
full history, loaded and verified per quarter. Keeping both targets would mean two sources and
dual-dialect SQL in every model.

## Decision
dbt targets Snowflake only, as SVC_DBT (role TRANSFORMER, warehouse WH_TRANSFORM), building into
the schemas Terraform created. The slice's DuckDB file stays on disk, no longer rebuilt.

## Consequences
- One dialect; sqlfluff lints as Snowflake.
- Parity was proven at the switch: Snowflake's mart equalled DuckDB's for 2026q3 exactly
  (5,190 filings, 642 flagged, 3,800 screened).
- Local development needs Snowflake credits (seconds of an extra-small warehouse per build).
