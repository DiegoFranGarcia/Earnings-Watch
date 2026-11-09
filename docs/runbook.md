# EarningsWatch runbook

How to operate the pipeline: what runs when, how to rerun or backfill safely, and what to do
when something breaks. Every step below is idempotent: rerunning it replaces exactly what it
covers and never duplicates data.

## How the pipeline runs

Each arrow is a data asset, not a clock: a DAG starts because new data arrived.

~~~text
SEC -> sec_daily_index (06:00 UTC daily) -> silver_daily_index -> snowflake_load_daily_index -> raw_daily_index -+
SEC -> sec_fsds_quarterly (quarterly) -> Spark on EMR -> silver_fsds -> snowflake_load -> raw_fsds --------------+-> dbt_build -> marts
SEC -> company_tickers_snapshot (07:00 UTC daily) -> bronze tickers
~~~

- Failures alert the Discord channel after the task's last retry, with a link to its log.
- sec_daily_index must finish by 12:00 UTC, or a deadline alert fires (nothing may have failed:
  look for a run that is stuck or never started).

## Running locally

~~~bash
cd airflow && docker compose up -d     # UI on http://localhost:8080
aws login --profile earnings-watch     # the containers share this session; it expires
~~~

**An expired `aws login` is the most common failure locally**: tasks that touch S3 or EMR fail or
retry. Run `aws login` again, then clear the failed tasks. On EC2 (Stage 7) an instance role
removes this problem.

## A fresh environment

Airflow writes two tables in `AUDIT` as `LOADER`; create them before the first run, so they exist
(and are readable by dbt) from the start. Idempotent:

~~~bash
uv run python scripts/create_audit_tables.py
~~~

## Rerun a failed task

Clear it in the UI (the task, then **Clear**), or:

~~~bash
docker compose exec airflow-scheduler airflow tasks clear <dag_id> -t '<task_regex>' -s <start> -e <end> -y
~~~

Every task writes one partition idempotently, so clearing and rerunning is always safe.

## Reload data into Snowflake

| What | How |
|---|---|
| One FSDS quarter | Trigger `snowflake_load` with `{"quarters": "2026q3"}` |
| Many quarters, or all | `{"quarters": "2009q2..2026q3"}` (about 25 minutes, one task per quarter) |
| One month of the daily index | Trigger `snowflake_load_daily_index` with `{"months": "2026-11"}` |

~~~bash
docker compose exec airflow-scheduler airflow dags trigger snowflake_load -c '{"quarters": "2026q3"}'
~~~

Each quarter or month is one transaction: delete, `COPY ... FORCE = TRUE`, count, and commit only
if the count matches (Spark's reconciliation record for FSDS, the files themselves for the daily
index). A mismatch fails immediately, with no retry, and rolls back: RAW is unchanged. Investigate
the source before rerunning. `dbt_build` follows automatically.

## A volume check failed

`dbt_build` starts with a volume gate. If the newest day of filings is under half its usual
volume, or the newest quarter under half (or over double) the same quarter a year earlier, the
build stops and **the marts keep their last good data**. Every result is in `AUDIT.DQ_RESULTS`.

1. Read the alert: it names the check, the day or quarter, and the ratio.
2. Investigate the source: is the SEC's file complete? Did the load load all of it?
3. If the data is wrong, fix the source and reload. If it is genuinely unusual (Christmas Eve
   really is quiet), trigger `dbt_build` by hand with `{"accept_volume": true}`.

~~~bash
docker compose exec airflow-scheduler airflow dags trigger dbt_build -c '{"accept_volume": true}'
~~~

## Reprocess an FSDS quarter from the SEC

Rerun `sec_fsds_quarterly` for the quarter's logical date. If the SEC republished the file, the
new version lands beside the old one under `version=...`, Spark converts that exact folder, and
the load and dbt follow.

## dbt

- **After changing the dbt project, rebuild the manifest** that the Airflow DAG reads:
  `cd dbt && uv run dbt parse`. Otherwise Airflow keeps building from the old one.
- **A seed's columns changed:** `uv run dbt seed --full-refresh -s <seed>` once.
- **An incremental model's columns changed** (`on_schema_change='fail'` stops it on purpose):
  `uv run dbt build --full-refresh -s <model>` once.
- **Run one model and its tests:** `uv run dbt build -s <model>`.
- **A test failed:** read the rows, never just raise the threshold. Problems in filer data warn;
  problems in our logic fail (ADR 8).

## Rotate a Snowflake service user's key

Snowflake holds two public keys per user, so a key can change with no downtime:

1. Generate a new pair in `~/.snowflake/keys/`: `openssl genrsa 2048 | openssl pkcs8 -topk8
   -inform PEM -out <user>_rsa_key_new.p8 -nocrypt`, then `openssl rsa -in ... -pubout`.
2. Set it as the user's second key (`rsa_public_key_2` in Terraform), and apply.
3. Point the clients at the new private key (`airflow/.env`, the compose mount), restart them.
4. Move the new key into `rsa_public_key`, remove `rsa_public_key_2`, apply, and delete the old
   private key.

## Tests

| Command | What it checks |
|---|---|
| `uv run pytest -q` | Unit tests, Spark parity, and the dbt project's guards |
| `scripts/test_dags.sh <image>` | Every DAG imports without network access; retries, timeouts, alerts and owners on every task (runs inside the Airflow image) |
| `cd dbt && uv run dbt build` | Every model, its contract and its tests, in Snowflake |

## Costs

Every Snowflake statement carries a query tag naming the pipeline step and the Airflow run:
`earningswatch:load:<run_id>` or `earningswatch:dbt:<run_id>`. `ACCOUNT_USAGE.QUERY_HISTORY`
and `QUERY_ATTRIBUTION_HISTORY` group credits by them.
