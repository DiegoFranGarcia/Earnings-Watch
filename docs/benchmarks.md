# Benchmark: DuckDB vs Spark (local and EMR Serverless)

**Question:** when is Spark worth it for converting the SEC's Financial Statement Data Sets
from tab-separated text to typed Parquet?

**Short answer:** not for speed at this size. A single-node DuckDB run on a laptop is about
4-5x faster than Spark anywhere, and adding EMR workers barely helps. Spark on EMR Serverless
is kept for a different reason: it keeps heavy compute off the Airflow host, costs nothing
when idle, and converted the full 17-year history for about $0.29.

## What was measured

- **Input:** the 8 most recent quarters (2024q4 to 2026q3), the largest in the history:
  4.5 GB of `sub.txt` and `num.txt`, **29,531,674** numbers.
- **The same conversion everywhere:** read as text with quote handling, cast, quarantine bad
  lines, remove exact duplicates, flag conflicting values, reconcile against the bronze
  manifests, write ZSTD Parquet, read back to verify.
- **Correctness:** every engine's output was compared with DuckDB's, quarter by quarter, by
  column types and by every row (`EXCEPT ALL` both ways): **24 of 24 identical**.

| Environment | Details |
|---|---|
| Laptop | Apple M1 Pro, 8 cores, 16 GB; data on local SSD; Docker stopped during runs |
| DuckDB | 1.5.6, the slice's converter (`spark/benchmarks/duckdb_baseline.py`) |
| Spark | 4.0.2 (`spark/jobs/fsds_to_silver.py`), Java 17 |
| EMR Serverless | emr-spark-8.0.0, ARM64 (Graviton), us-east-1, reading and writing S3 |

## Results: 8 quarters, 29.5 million rows

| Engine | Conversion | Wall time | Rows/s | Cost |
|---|---:|---:|---:|---:|
| DuckDB, laptop | **46.7 s** | 46.7 s | **632,000** | $0 |
| Spark `local[*]`, laptop | 195 s | 195 s | 151,000 | $0 |
| Spark on EMR, small: driver + 2 executors, 12 vCPU | 244 s | 6 min 20 s | 121,000 | $0.052 |
| Spark on EMR, large: driver + 6 executors, 28 vCPU | 217 s | 5 min 13 s | 136,000 | $0.069 |

- *Conversion* is the job's own timer; *wall time* includes EMR start-up (about 1-2 minutes).
- Cost is EMR's billed usage at November 2026 ARM rates ($0.042094 per vCPU-hour,
  $0.004628 per GB-hour). DuckDB's peak memory was 3.18 GB; Spark's driver was given 4 GB
  locally and about 16 GB per worker on EMR.

## Full history: 70 quarters, 188,865,271 rows (EMR small, one job)

| Measure | Value |
|---|---:|
| Conversion | 1,438 s (24 min) |
| Wall time, submission to finish | about 27 min |
| Billed | 4.836 vCPU-hours, 19.342 GB-hours |
| **Cost** | **about $0.29** |
| Lines quarantined / cast failures | 0 / 0 |
| Output | 3.06 GB of Parquet (bronze text: about 35 GB) |

*Estimate, not measured:* at DuckDB's measured rate, the full history would take about
5 minutes on the laptop, if all of it were downloaded first (about 25 GB).

## Findings

1. **DuckDB wins at this scale**: 4.2x faster than local Spark, about 5x faster than EMR.
   The data fits comfortably on one machine; Spark's coordination is pure overhead here.
2. **More EMR workers barely help**: +133% vCPU bought an 11% speed-up for 33% more cost.
   Each quarter runs about a dozen small Spark steps in sequence (counts, writes, read-backs),
   each with fixed overhead, so extra executors mostly sit idle. The large run also averaged
   about 16 billed vCPU of the 28 requested: on a 4-minute job, some workers arrive late.
3. **Start-up dominates short EMR jobs**: about 2.5 minutes before a single job runs. Running
   70 quarters as one job instead of 70 jobs saved roughly three hours of waiting.
4. **Laptop and EMR Spark are close** (195 s vs 244 s) despite 8 cores vs 12 vCPU: EMR reads and
   writes S3 over the network, the laptop reads a local SSD.

## Why Spark stays

Not speed: separation and cost shape. Spark runs off the Airflow host (which stays small),
scales to zero between quarterly runs, and processed the entire history for under 30 cents.
DuckDB on the Airflow host is a valid alternative at this size, and would be the first choice
if the host had memory to spare.

## What would make Spark faster

- **Convert several quarters concurrently** within one job, so idle executors have work: the
  bottleneck is sequential per-quarter steps, not compute.
- **Fewer actions per quarter**: compute the row counts for the reconciliation in one
  aggregation instead of several separate counts.

## Reproduce

```bash
# DuckDB and local Spark (after downloading the 8 quarters to data/bench/bronze)
uv run python spark/benchmarks/duckdb_baseline.py --quarters 2024q4..2026q3 \
    --bronze-root data/bench/bronze --silver-root data/bench/silver_duckdb
uv run python spark/jobs/fsds_to_silver.py --local --quarters 2024q4..2026q3 \
    --bronze-root data/bench/bronze --silver-root data/bench/silver_spark_local

# Correctness, per quarter
uv run python slice/compare_silver.py data/bench/silver_duckdb data/bench/silver_spark_local 2026q3
```
