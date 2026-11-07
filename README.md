# EarningsWatch

**Flags public companies whose reported profits are outrunning their cash, from 17 years of
SEC filings.**

[![CI](https://github.com/DiegoFranGarcia/Earnings-Watch/actions/workflows/ci.yml/badge.svg)](https://github.com/DiegoFranGarcia/Earnings-Watch/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

When net income rises while operating cash flow falls, the gap is made of *accruals*: profit
not (yet) backed by cash. Accounting research links large accruals to lower-quality earnings
and later restatements. EarningsWatch builds the data platform to screen for that pattern
across every XBRL filer since 2009: idempotent ingestion, a verified lake, Spark on AWS,
and tested models.

> A screen for where to look harder, **not investment advice**.

## In numbers

| | |
|---|---:|
| SEC financial statement numbers converted and verified | **188,865,271** |
| Quarters of history (2009 Q2 to 2026 Q3) | **70** |
| Raw files in the lake, every one with a checksum receipt | **810+** (35.5 GB) |
| Lines quarantined / values that failed their type cast, across all history | **0 / 0** |
| Full-history conversion on Spark (EMR Serverless) | **24 min, about $0.29** |
| Spark output identical to the reference DuckDB converter | **24 of 24** quarter checks |
| Automated tests (Python + dbt) | **140+** Python, 35 dbt checks |
| Running cost | **about $1/month** (storage), cents per Spark run |

## Architecture

```mermaid
flowchart LR
    SEC["SEC EDGAR<br/>daily index · tickers<br/>quarterly data sets"]
    AF["Airflow 3.3<br/>3 DAGs · shared rate-limit pool<br/>deferrable tasks"]
    subgraph AWS["AWS · us-east-1"]
        BR[("S3 bronze<br/>files exactly as published<br/>+ checksum receipts")]
        EMR["Spark 4.0<br/>EMR Serverless · Graviton<br/>scales to zero"]
        SI[("S3 silver<br/>typed ZSTD Parquet")]
    end
    DBT["dbt<br/>DuckDB today · Snowflake next"]
    ST["Streamlit<br/>screener"]
    SEC -->|"polite client<br/>≤ 5 req/s"| AF --> BR
    AF -. "submits, waits deferred" .-> EMR
    BR --> EMR --> SI --> DBT --> ST
```

Airflow orchestrates and never crunches data: downloads go to **bronze**, immutable and
receipted; Spark on **EMR Serverless** turns them into typed **silver** Parquet and stops; dbt
models the answer. Airflow currently runs in Docker locally; it moves to EC2 in a later stage.

## Stack, and why

| Tool | Why it is here |
|---|---|
| **Airflow 3.3** | Logical-date scheduling, backfills, pools as a cross-DAG SEC rate limit, deferrable waits that hold no worker |
| **S3 (bronze / silver)** | Immutable raw files with receipts; open Parquet any engine can read |
| **Spark 4.0 on EMR Serverless** | Keeps heavy compute off the orchestrator; bills per second; idle costs nothing ([ADR 2](docs/adr/0002-run-spark-on-emr-serverless-graviton.md)) |
| **DuckDB** | The single-node baseline Spark is benchmarked against, and the local warehouse for dbt |
| **dbt** | Tested, documented models with unit tests and enforced contracts |
| **Terraform** | Every AWS resource as reviewed code, with cost caps built in |
| **GitHub Actions** | Lint and every test, including Spark on Java 17, on each push |

Decisions are recorded as [architecture decision records](docs/adr/).

## Design decisions worth asking about

- **Bronze receipts are the commit marker.** Each file's manifest is written last, so a
  rerun skips anything complete. Rerunning the full history (741 runs) wrote **zero** files.
- **Republished data never overwrites history.** A changed SEC file is detected by a cheap
  HEAD check, verified by checksum, and kept beside the original under `version=`.
- **Spark reads back what it wrote.** A job once reported success while its output was never
  committed to S3; now every partition is re-read and counted before success is claimed.
- **Parity, not trust.** The Spark job is tested against the original DuckDB converter on a
  deliberately awkward fixture, and on real data: identical columns, types and rows.
- **Cost guardrails before resources.** EMR has no idle capacity, auto-stops, and has hard
  caps on CPU, memory, disk and concurrent runs; there is no NAT gateway.

## Benchmark: is Spark worth it here?

On the 8 largest quarters (29.5 million rows), measured on the same input:

| Engine | Time | Cost |
|---|---:|---:|
| DuckDB, laptop (M1 Pro) | **47 s** | $0 |
| Spark, laptop | 195 s | $0 |
| Spark, EMR, 12 vCPU | 244 s | $0.05 |
| Spark, EMR, 28 vCPU | 217 s | $0.07 |

**DuckDB wins at this size, and more Spark workers barely help** (+133% vCPU, −11% time): the
job is bound by sequential per-quarter steps, not compute. Spark stays for isolation and
cost shape, not speed. Full method and analysis: [docs/benchmarks.md](docs/benchmarks.md).

## Data quality, found and handled

Every check that fired was investigated against the data before anything was changed:

- **The SEC's documentation was wrong about quoting:** fields containing tabs are quoted.
  Naive parsing silently shifted rows into the wrong columns; reconciliation caught it.
- **Three business days had no EDGAR index** (a national day of mourning, two Christmas-week
  closures). The pipeline skipped them by design and the reconciliation flagged them; SEC
  announcements confirmed all three.
- **A filer dated figures to the year 204.** Reported as a warning, not a pipeline failure.
- **Conflicting values for the same reported number** have grown since 2024 Q3 (up to 98 rows
  a quarter); they are kept and flagged for the models to resolve, never silently dropped.

## Status

| Stage | |
|---|---|
| 0. Foundations: AWS guardrails, Terraform, CI | ✅ |
| 1. Ingestion: 3 Airflow pipelines, full history backfilled and reconciled | ✅ |
| 2. Spark on EMR Serverless, benchmark published | ✅ |
| 3. Snowflake warehouse | next |
| 4. dbt star schema: company history, restatements, timeliness | |
| 5–9. Orchestration end to end, observability, deployment, CI/CD, demo | |

A thin end-to-end slice (one quarter, DuckDB, dbt, Streamlit) was built first, so modelling
problems surfaced in week three rather than week fifteen.

## Run it

```bash
uv sync                                    # Python 3.12 environment
uv run pytest -q                           # all tests (Spark tests need Java 17)

cd airflow && docker compose up -d         # Airflow on http://localhost:8080
cd dbt && uv run dbt build                 # models and tests (slice, DuckDB)
uv run streamlit run app/streamlit_app.py  # the screener
```

Infrastructure lives in `infra/` (Terraform); the Spark job in `spark/`, packaged per commit
with `scripts/package_spark_job.sh`.

## License

MIT
