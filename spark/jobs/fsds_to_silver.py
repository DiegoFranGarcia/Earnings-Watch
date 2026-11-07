"""Spark job: turn one FSDS quarter's sub.txt and num.txt into typed, validated silver Parquet.

The same file runs on a laptop and on EMR Serverless. It:

- reads every column as text, honouring the SEC's quotes, then casts deliberately;
- quarantines lines that do not parse, keeping their raw text;
- removes exact duplicates, and flags conflicting values for the same key;
- reconciles every row against the bronze manifests, and fails on any gap;
- replaces exactly this quarter's silver partitions (dynamic partition overwrite);
- writes a reconciliation record beside silver.

Several quarters in one job (each still reconciled and verified on its own):

    ... --quarters 2009q2..2026q3 --bronze-root s3://<lake>/bronze/source=fsds ...

Local run, from the repository root:

    uv run python spark/jobs/fsds_to_silver.py --local --quarter 2026q3 \
        --bronze-root data/bronze/fsds --silver-root data/silver_spark

On EMR, spark-submit chooses the cluster, so --local is left out.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make spark/lib importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.errors import AnalysisException  # noqa: E402
from pyspark.sql import DataFrame, SparkSession  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

from lib.quarters import expand  # noqa: E402
from lib.schemas import NUM_CASTS, NUM_COLUMNS, NUM_KEY, SUB_CASTS, SUB_COLUMNS  # noqa: E402
from lib.transforms import (  # noqa: E402
    count_cast_failures,
    good_rows,
    quarantined_rows,
    read_raw,
    silver_num,
    typed,
)

QUARANTINE_LIMIT = 0.0001  # the plan's threshold: fail if more than 0.01% of rows are bad


class ReconciliationError(RuntimeError):
    """Rows went missing, or too many rows were bad."""


@dataclass(frozen=True)
class TableCheck:
    table: str
    expected_rows: int  # data rows according to the bronze manifest
    rows_read: int
    rows_quarantined: int
    cast_failures: int
    duplicates_removed: int
    rows_written: int


@dataclass(frozen=True)
class Reconciliation:
    quarter: str
    sub: TableCheck
    num: TableCheck
    num_rows_without_filing: int
    keys_with_conflicting_values: int
    rows_with_conflicting_values: int
    seconds: float


def session(local: bool, app_name: str = "fsds_to_silver") -> SparkSession:
    """A Spark session: all local cores with --local, otherwise the cluster spark-submit chose.

    Local mode is an explicit choice, not detected: a SparkConf created before Spark starts
    cannot see spark-submit's settings, so detection would wrongly pick local mode on EMR.
    """
    builder = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.sql.parquet.compression.codec", "zstd")
    )
    if local:
        builder = builder.master("local[*]").config("spark.driver.memory", "4g")
    return builder.getOrCreate()


def expected_rows(spark: SparkSession, data_path: str) -> int:
    """Data rows according to the file's bronze manifest (its line count minus the header)."""
    text = "\n".join(row.value for row in spark.read.text(data_path + ".manifest.json").collect())
    return int(json.loads(text)["line_count"]) - 1


def _write_partition(df: DataFrame, path: str, quarter: str) -> None:
    """Replace exactly this quarter's partition under `path`, as one ZSTD Parquet file."""
    (
        df.withColumn("source_quarter", F.lit(quarter))
        .repartition(1)  # a quarter is tens of MB of Parquet: one file avoids small files
        .write.mode("overwrite")
        .partitionBy("source_quarter")
        .parquet(path)
    )


def verify_partition(spark: SparkSession, path: str, quarter: str, expected: int) -> None:
    """Read back a written partition and fail unless exactly `expected` rows are readable.

    A job can report success while its output never becomes visible (an uncommitted S3
    upload, for example). This turns that silent failure into a loud one.
    """
    partition = f"{path}/source_quarter={quarter}"
    try:
        readable = spark.read.parquet(partition).count()
    except AnalysisException as exc:
        raise ReconciliationError(f"{partition}: no readable Parquet after writing") from exc
    if readable != expected:
        raise ReconciliationError(
            f"{partition}: wrote {expected:,} rows, but {readable:,} are readable"
        )


def run(
    spark: SparkSession,
    quarter: str,
    bronze_root: str | None,
    silver_root: str,
    quarantine_limit: float = QUARANTINE_LIMIT,
    *,
    bronze_folder: str | None = None,
) -> Reconciliation:
    """Convert one quarter. bronze_folder, when given, is the exact folder to read (for a
    republished quarter, its version= folder); otherwise it is bronze_root/quarter=..."""
    started = time.perf_counter()
    if bronze_folder:
        folder = bronze_folder.rstrip("/")
    elif bronze_root:
        folder = f"{bronze_root.rstrip('/')}/quarter={quarter}"
    else:
        raise ValueError("give bronze_root or bronze_folder")
    silver = silver_root.rstrip("/")
    raw = {
        "sub": read_raw(spark, f"{folder}/sub.txt", SUB_COLUMNS),
        "num": read_raw(spark, f"{folder}/num.txt", NUM_COLUMNS),
    }
    expected = {t: expected_rows(spark, f"{folder}/{t}.txt") for t in raw}
    good = {t: good_rows(df) for t, df in raw.items()}
    sub = typed(good["sub"], SUB_COLUMNS, SUB_CASTS).cache()
    num_typed = typed(good["num"], NUM_COLUMNS, NUM_CASTS)
    num = silver_num(num_typed, sub).cache()

    checks = {}
    for table, casts, out in (("sub", SUB_CASTS, sub), ("num", NUM_CASTS, num)):
        read = good[table].count()
        written = out.count()
        checks[table] = TableCheck(
            table=table,
            expected_rows=expected[table],
            rows_read=read,
            rows_quarantined=quarantined_rows(raw[table]).count(),
            cast_failures=count_cast_failures(good[table], casts),
            duplicates_removed=read - written,
            rows_written=written,
        )
    conflicts = num.filter("has_key_conflict")
    rec = Reconciliation(
        quarter=quarter,
        sub=checks["sub"],
        num=checks["num"],
        num_rows_without_filing=num_typed.join(sub, "adsh", "left_anti").count(),
        keys_with_conflicting_values=conflicts.select(*NUM_KEY).distinct().count(),
        rows_with_conflicting_values=conflicts.count(),
        seconds=0.0,
    )
    _enforce(rec, quarantine_limit)

    _write_partition(sub, f"{silver}/fsds/sub", quarter)
    _write_partition(num, f"{silver}/fsds/num", quarter)
    verify_partition(spark, f"{silver}/fsds/sub", quarter, checks["sub"].rows_written)
    verify_partition(spark, f"{silver}/fsds/num", quarter, checks["num"].rows_written)
    for table in ("sub", "num"):
        if checks[table].rows_quarantined:
            _write_partition(
                quarantined_rows(raw[table]), f"{silver}/_quarantine/fsds/{table}", quarter
            )
    rec = replace(rec, seconds=round(time.perf_counter() - started, 1))
    record = spark.createDataFrame([(json.dumps(asdict(rec)),)], "record string")
    record.coalesce(1).write.mode("overwrite").text(
        f"{silver}/_reconciliation/fsds/source_quarter={quarter}"
    )
    return rec


def _enforce(rec: Reconciliation, quarantine_limit: float) -> None:
    for check in (rec.sub, rec.num):
        accounted = check.rows_read + check.rows_quarantined
        if accounted != check.expected_rows:
            raise ReconciliationError(
                f"{check.table}: manifest says {check.expected_rows:,} rows, "
                f"but {accounted:,} were read or quarantined"
            )
        bad = check.rows_quarantined + check.cast_failures
        if bad > check.expected_rows * quarantine_limit:
            raise ReconciliationError(
                f"{check.table}: {bad:,} bad rows is over the "
                f"{quarantine_limit:.2%} limit of {check.expected_rows:,}"
            )


def run_many(
    spark: SparkSession,
    quarters: list[str],
    bronze_root: str,
    silver_root: str,
    quarantine_limit: float = QUARANTINE_LIMIT,
) -> tuple[list[Reconciliation], list[tuple[str, str]]]:
    """Convert quarters one after another in this session; a failed quarter does not stop
    the rest. Returns the reconciliations and the (quarter, error) failures."""
    done: list[Reconciliation] = []
    failed: list[tuple[str, str]] = []
    for quarter in quarters:
        try:
            done.append(run(spark, quarter, bronze_root, silver_root, quarantine_limit))
            _print_line(done[-1])
        except Exception as exc:  # noqa: BLE001 - recorded, reported, and fails the job below
            failed.append((quarter, f"{type(exc).__name__}: {exc}".splitlines()[0][:300]))
            print(f"{quarter:<8} FAILED  {failed[-1][1]}", flush=True)
        finally:
            spark.catalog.clearCache()  # each quarter caches its data; release it before the next
    return done, failed


def _print_line(rec: Reconciliation) -> None:
    print(
        f"{rec.quarter:<8} sub {rec.sub.rows_written:>8,}  num {rec.num.rows_written:>11,}  "
        f"quarantined {rec.sub.rows_quarantined + rec.num.rows_quarantined:>5,}  "
        f"cast fails {rec.sub.cast_failures + rec.num.cast_failures:>5,}  "
        f"dupes {rec.num.duplicates_removed:>7,}  "
        f"conflicts {rec.rows_with_conflicting_values:>6,}  {rec.seconds:>6.1f}s",
        flush=True,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Convert FSDS quarters to silver Parquet.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--quarter", help="one quarter, for example 2026q3")
    which.add_argument("--quarters", help="a list or range, for example 2009q2..2026q3")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--bronze-root", help="folder holding quarter=YYYYqN/")
    source.add_argument("--bronze-folder", help="the exact folder holding sub.txt and num.txt")
    parser.add_argument("--silver-root", required=True, help="silver folder or s3:// prefix")
    parser.add_argument("--local", action="store_true", help="run on this machine's cores")
    args = parser.parse_args(argv)
    if args.quarters and args.bronze_folder:
        parser.error("--bronze-folder names one quarter's folder: use it with --quarter")

    spark = session(local=args.local)
    print(f"spark master: {spark.sparkContext.master}")
    spark.sparkContext.setLogLevel("WARN")

    if args.quarter:
        rec = run(
            spark,
            args.quarter.strip().lower(),
            args.bronze_root,
            args.silver_root,
            bronze_folder=args.bronze_folder,
        )
        _print_table(rec)
        spark.stop()
        return

    quarters = expand(args.quarters)
    print(f"converting {len(quarters)} quarters: {quarters[0]}..{quarters[-1]}", flush=True)
    started = time.perf_counter()
    done, failed = run_many(spark, quarters, args.bronze_root, args.silver_root)
    spark.stop()
    rows = sum(r.num.rows_written for r in done)
    print(f"\n{len(done)} quarters converted, {len(failed)} failed, "
          f"{rows:,} numbers written in {time.perf_counter() - started:.0f}s")  # fmt: skip
    if failed:
        print("failed quarters: " + ", ".join(q for q, _ in failed))
        sys.exit(1)  # a non-zero exit marks the EMR job FAILED


def _print_table(rec: Reconciliation) -> None:
    print(f"\n{'table':<5} {'expected':>12} {'read':>12} {'quarantined':>12} "
          f"{'cast fails':>11} {'dupes':>7} {'written':>12}")  # fmt: skip
    for check in (rec.sub, rec.num):
        print(
            f"{check.table:<5} {check.expected_rows:>12,} {check.rows_read:>12,} "
            f"{check.rows_quarantined:>12,} {check.cast_failures:>11,} "
            f"{check.duplicates_removed:>7,} {check.rows_written:>12,}"
        )
    print(f"\nnum rows with no matching filing in sub: {rec.num_rows_without_filing:,}")
    print(f"keys with conflicting values (kept, flagged): {rec.keys_with_conflicting_values:,} "
          f"({rec.rows_with_conflicting_values:,} rows)")  # fmt: skip
    print(f"\n{rec.quarter} converted in {rec.seconds}s")


if __name__ == "__main__":
    main()
