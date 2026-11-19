# 18. One deployed environment, whose database is EARNINGSWATCH_DEV

## Context

Terraform creates three Snowflake databases: `EARNINGSWATCH`, `EARNINGSWATCH_DEV` and
`EARNINGSWATCH_CI`. The only deployed stack is `infra/envs/dev`. Its host loads into the
database set as `snowflake_database` (`EARNINGSWATCH_DEV`), and dbt builds wherever its profile
points: `EARNINGSWATCH_DEV`, unless `DBT_SNOWFLAKE_DATABASE` says otherwise, which the host does
not set. On 2026-11-19, `EARNINGSWATCH` held no tables, and the docs on the public site listed
every model in `EARNINGSWATCH_DEV`. The runbook and earlier docs called what the host runs
"production".

## Decision

- There is one deployed environment, dev, and its database is `EARNINGSWATCH_DEV`. Where the
  runbook and other docs say production, they mean this environment: what the host runs and
  what the public site shows.
- `EARNINGSWATCH` stays, empty, reserved for a production environment. An empty database costs
  nothing, and its schemas and grants already exist.
- The pipeline does not move there now. Moving would mean reloading and rebuilding everything
  (`fct_reported_facts` alone is 189 million rows, 7.4 GB) for a change of name.

## Consequences

- The site, its dbt docs and every number in the README come from `EARNINGSWATCH_DEV`.
- Until a second environment exists, the profile's default database and the host's
  `snowflake_database` must agree. Both are `EARNINGSWATCH_DEV`.
- A production environment, when it comes, is a second root, `infra/envs/prod`, with
  `snowflake_database = "EARNINGSWATCH"`. Its host sets `DBT_SNOWFLAKE_DATABASE` from that same
  value, so the loads and dbt cannot point at different databases.
