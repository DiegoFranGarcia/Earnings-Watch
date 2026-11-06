# 2. Run Spark on EMR Serverless, on Graviton (ARM64)

## Context

Converting 70 quarters of FSDS text (about 35 GB) to Parquet is the heaviest compute in
the project. The Airflow host should orchestrate, not crunch data, and the work runs only
a few times a year after the initial backfill. Locally, PySpark 4.0.2 reproduces the
DuckDB converter exactly (identical rows on 2026q3's 3.9 million numbers).

Prices checked in November 2026 for us-east-1: x86 workers cost $0.052624 per vCPU-hour
and $0.0057785 per GB-hour; ARM (Graviton) workers cost about 20% less.

## Decision

- EMR Serverless, release emr-spark-8.0.0 (Spark 4.0.2, matching local PySpark).
- ARM64 workers: the job is pure Python and Spark, so the processor does not matter.
- No pre-initialised capacity, auto-stop after 15 idle minutes, and a maximum capacity of
  32 vCPU / 128 GB as a hard ceiling on spend (about $1.94 an hour at worst).
- At most 2 concurrent job runs, and a 640 GB disk ceiling (AWS's defaults are 15 runs
  and 400,000 GB); declaring the scheduler also stops a perpetual Terraform diff.
- No VPC: jobs reach S3 without one, so no NAT gateway or public IPv4 charges.
- A job role limited to reading bronze FSDS and the job code, and writing silver and logs.

## Consequences

- Nothing bills while idle; a typical quarter is estimated at a few cents (to be replaced
  by measurements in the benchmark).
- Jobs have no internet access. That is intended: downloading stays in Airflow, which
  enforces the SEC's rate limit; Spark only ever reads the lake.
- If a library ever needs x86, switching architecture is a one-line change.
