# EarningsWatch

![CI](https://github.com/DiegoFranGarcia/Earnings-Watch/actions/workflows/ci.yml/badge.svg)

Flags public companies whose reported earnings outrun their cash, using 17 years of SEC EDGAR filings.

**Status:** Stage 1, ingestion. Not investment advice.

## Stack

Airflow 3 · Spark on EMR Serverless · Snowflake · dbt · Terraform · AWS

## Run Airflow locally

```bash
cd airflow
docker compose up -d   # UI at http://localhost:8080
```
