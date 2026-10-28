"""Slice step 2: turn one FSDS quarter's text files into typed Parquet with DuckDB.

For sub.txt and num.txt this:

- reads every column as text with an explicit column list (nothing is guessed),
  honouring the SEC's double quotes around fields that contain tabs,
- casts each column deliberately; a value that fails its cast is counted,
- quarantines malformed lines instead of crashing or silently dropping them,
- removes exact duplicate rows, and flags rows that share num's eight-column key
  but report different values (has_key_conflict) instead of silently picking one,
- enriches num with filing attributes from sub (cik, form, filed, fy, fp),
- reconciles row counts with the bronze manifests, and fails on any gap,
- writes ZSTD-compressed Parquet locally (data/silver) and to silver/ in S3,
- saves quarantined lines, with their raw text, to silver/_quarantine/.

This is also the single-node DuckDB baseline that Spark is benchmarked against in Stage 2.

Usage:
    PYTHONPATH=airflow/dags uv run python slice/fsds_to_parquet.py 2026q3
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import boto3
import duckdb

from earningswatch import fsds
from earningswatch.bronze import download_verified
from earningswatch.config import load_settings

log = logging.getLogger(__name__)

DATA_DIR = Path("data")
QUARANTINE_LIMIT = 0.0001  # the plan's threshold: fail if more than 0.01% of rows are bad

SUB_COLUMNS = (
    "adsh", "cik", "name", "sic", "countryba", "stprba", "cityba", "zipba", "bas1", "bas2",
    "baph", "countryma", "stprma", "cityma", "zipma", "mas1", "mas2", "countryinc", "stprinc",
    "ein", "former", "changed", "afs", "wksi", "fye", "form", "period", "fy", "fp", "filed",
    "accepted", "prevrpt", "detail", "instance", "nciks", "aciks",
)  # fmt: skip
NUM_COLUMNS = (
    "adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value", "footnote",
)  # fmt: skip
NUM_KEY = ("adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg")

_DATE = "TRY_STRPTIME({c}, '%Y%m%d')::DATE"
_INT = "TRY_CAST({c} AS INTEGER)"
_BOOL = "CASE {c} WHEN '1' THEN TRUE WHEN '0' THEN FALSE END"

# Every column not listed here stays text (codes such as fye, ein and zip keep their zeros).
SUB_CASTS = {
    "cik": "TRY_CAST({c} AS BIGINT)",
    "sic": _INT,
    "changed": _DATE,
    "wksi": _BOOL,
    "period": _DATE,
    "fy": _INT,
    "filed": _DATE,
    "accepted": "TRY_CAST({c} AS TIMESTAMP)",
    "prevrpt": _BOOL,
    "detail": _BOOL,
    "nciks": _INT,
}
NUM_CASTS = {
    "ddate": _DATE,
    "qtrs": _INT,
    "value": "TRY_CAST({c} AS DECIMAL(28, 4))",  # exactly as the SEC defines it
}


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
    sub: TableCheck
    num: TableCheck
    num_rows_without_filing: int  # num rows whose adsh is not in sub
    keys_with_conflicting_values: int  # same eight-column key, different values
    rows_with_conflicting_values: int  # the rows behind those keys, all kept and flagged


def convert(
    con: duckdb.DuckDBPyConnection,
    sub_path: Path,
    num_path: Path,
    expected_sub_rows: int,
    expected_num_rows: int,
    quarantine_limit: float = QUARANTINE_LIMIT,
) -> Reconciliation:
    """Build typed `sub` and `num` tables in `con`, and check every row is accounted for."""
    _read_raw(con, "sub", sub_path, SUB_COLUMNS)
    _read_raw(con, "num", num_path, NUM_COLUMNS)

    sub_select = _select_list(SUB_COLUMNS, SUB_CASTS)
    num_select = _select_list(NUM_COLUMNS, NUM_CASTS)
    con.execute(f"CREATE OR REPLACE TABLE sub AS SELECT {sub_select} FROM raw_sub")  # noqa: S608
    con.execute(f"CREATE OR REPLACE TABLE num_typed AS SELECT {num_select} FROM raw_num")  # noqa: S608

    every_column = ", ".join(NUM_COLUMNS)
    key = ", ".join(f"d.{column}" for column in NUM_KEY)
    con.execute(f"""
        CREATE OR REPLACE TABLE num AS
        WITH deduplicated AS (
            -- an exact duplicate repeats every column, so it carries no new information
            SELECT * FROM num_typed
            QUALIFY row_number() OVER (PARTITION BY {every_column}) = 1
        )
        SELECT
            d.*,
            s.cik, s.form, s.filed, s.fy, s.fp,
            d.segments IS NULL AND d.coreg IS NULL AS is_entity_total,
            CASE WHEN d.qtrs = 0 THEN 'instant' ELSE 'duration' END AS period_type,
            -- same key, different values: keep every row, flag it, decide later in dbt
            count(*) OVER (PARTITION BY {key}) > 1 AS has_key_conflict
        FROM deduplicated AS d
        LEFT JOIN sub AS s USING (adsh)
    """)  # noqa: S608 - column names are constants defined above

    sub_check = _table_check(con, "sub", expected_sub_rows, SUB_CASTS, "sub")
    num_check = _table_check(con, "num", expected_num_rows, NUM_CASTS, "num")
    reconciliation = Reconciliation(
        sub=sub_check,
        num=num_check,
        num_rows_without_filing=_scalar(
            con, "SELECT count(*) FROM num_typed ANTI JOIN sub USING (adsh)"
        ),
        keys_with_conflicting_values=_scalar(
            con,
            f"""SELECT count(*) FROM (
                    SELECT 1 FROM num WHERE has_key_conflict GROUP BY {", ".join(NUM_KEY)}
                )""",  # noqa: S608 - column names are constants defined above
        ),
        rows_with_conflicting_values=_scalar(
            con, "SELECT count(*) FROM num WHERE has_key_conflict"
        ),
    )
    _enforce(reconciliation, quarantine_limit)
    return reconciliation


def write_parquet(con: duckdb.DuckDBPyConnection, silver_dir: Path, quarter: str) -> dict:
    """Write each table as one ZSTD Parquet file in a Hive-style partition folder."""
    written = {}
    for table in ("sub", "num"):
        folder = silver_dir / "fsds" / table / f"source_quarter={quarter}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "part-0.parquet"
        con.execute(f"COPY {table} TO '{path}' (FORMAT parquet, COMPRESSION zstd)")
        written[table] = path
    return written


def write_quarantine(con: duckdb.DuckDBPyConnection, silver_dir: Path, quarter: str) -> dict:
    """Save each table's rejected lines (number, error, raw text); None when there are none."""
    written = {}
    for table in ("sub", "num"):
        folder = silver_dir / "_quarantine" / "fsds" / table / f"source_quarter={quarter}"
        path = folder / "rejects.parquet"
        path.unlink(missing_ok=True)
        if _scalar(con, f"SELECT count(*) FROM rejects_{table}") == 0:  # noqa: S608
            written[table] = None
            continue
        folder.mkdir(parents=True, exist_ok=True)
        con.execute(f"""
            COPY (
                SELECT line, any_value(error_type) AS error_type,
                       any_value(error_message) AS error_message,
                       any_value(csv_line) AS raw_line
                FROM rejects_{table} GROUP BY line ORDER BY line
            ) TO '{path}' (FORMAT parquet)
        """)  # noqa: S608 - names are constants
        written[table] = path
    return written


# -- internals ----------------------------------------------------------------


def _read_raw(
    con: duckdb.DuckDBPyConnection, name: str, path: Path, columns: tuple[str, ...]
) -> None:
    spec = "{" + ", ".join(f"'{column}': 'VARCHAR'" for column in columns) + "}"
    con.execute(
        f"""
        CREATE OR REPLACE TABLE raw_{name} AS
        SELECT * FROM read_csv(
            ?, delim = '\t', header = true, quote = '"', escape = '"',
            columns = {spec},
            store_rejects = true,
            rejects_table = 'rejects_{name}', rejects_scan = 'rejects_scan_{name}'
        )
        """,  # noqa: S608 - names are constants; the path is a bound parameter
        [str(path)],
    )


def _select_list(columns: tuple[str, ...], casts: dict[str, str]) -> str:
    return ", ".join(
        f"{casts[column].format(c=column)} AS {column}" if column in casts else column
        for column in columns
    )


def _table_check(
    con: duckdb.DuckDBPyConnection,
    table: str,
    expected_rows: int,
    casts: dict[str, str],
    raw: str,
) -> TableCheck:
    rows_read = _scalar(con, f"SELECT count(*) FROM raw_{raw}")  # noqa: S608
    failures = " + ".join(
        f"count(*) FILTER (WHERE {column} IS NOT NULL AND {expr.format(c=column)} IS NULL)"
        for column, expr in casts.items()
    )
    cast_failures = _scalar(con, f"SELECT {failures} FROM raw_{raw}")  # noqa: S608
    written = _scalar(con, f"SELECT count(*) FROM {table}")  # noqa: S608
    return TableCheck(
        table=table,
        expected_rows=expected_rows,
        rows_read=rows_read,
        rows_quarantined=_scalar(con, f"SELECT count(DISTINCT line) FROM rejects_{raw}"),  # noqa: S608
        cast_failures=cast_failures,
        duplicates_removed=rows_read - written,
        rows_written=written,
    )


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


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    return con.execute(sql).fetchone()[0]


def _upload_partition(s3: Any, bucket: str, local: Path | None, key: str) -> None:
    """Replace one silver partition: delete what is there, then upload the new file (if any)."""
    prefix = key.rsplit("/", 1)[0] + "/"
    stale = s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
    for obj in stale:
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    if local is not None:
        s3.upload_file(str(local), bucket, key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert one FSDS quarter to typed Parquet.")
    parser.add_argument("quarter", help="for example 2026q3")
    quarter = fsds.validate_quarter(parser.parse_args().quarter)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings()
    s3 = boto3.client("s3")

    started = time.perf_counter()
    local = {}
    expected = {}
    for member in ("sub.txt", "num.txt"):
        dest = DATA_DIR / "bronze" / "fsds" / f"quarter={quarter}" / member
        manifest = download_verified(
            s3, settings.lake_bucket, fsds.member_key(quarter, member), dest
        )
        local[member] = dest
        expected[member] = (manifest.line_count or 1) - 1  # minus the header line
    fetched = time.perf_counter()

    con = duckdb.connect()
    rec = convert(con, local["sub.txt"], local["num.txt"], expected["sub.txt"], expected["num.txt"])
    written = write_parquet(con, DATA_DIR / "silver", quarter)
    quarantined = write_quarantine(con, DATA_DIR / "silver", quarter)
    converted = time.perf_counter()

    for table, path in written.items():
        key = f"silver/fsds/{table}/source_quarter={quarter}/part-0.parquet"
        _upload_partition(s3, settings.lake_bucket, path, key)
    for table, path in quarantined.items():
        key = f"silver/_quarantine/fsds/{table}/source_quarter={quarter}/rejects.parquet"
        _upload_partition(s3, settings.lake_bucket, path, key)
    record = {
        "quarter": quarter,
        **asdict(rec),
        "seconds": {
            "fetch": round(fetched - started, 1),
            "convert_and_write": round(converted - fetched, 1),
        },
        "bytes": {
            table: {"text": local[f"{table}.txt"].stat().st_size, "parquet": path.stat().st_size}
            for table, path in written.items()
        },
    }
    record_key = f"silver/_reconciliation/fsds/source_quarter={quarter}.json"
    s3.put_object(
        Bucket=settings.lake_bucket,
        Key=record_key,
        Body=json.dumps(record, indent=2, default=str).encode(),
        ContentType="application/json",
    )

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
    for table, path in quarantined.items():
        if path is not None:
            print(f"quarantined {table} lines saved: {path}")
    for table, sizes in record["bytes"].items():
        ratio = sizes["text"] / sizes["parquet"]
        print(f"{table}: {sizes['text']:,} bytes of text -> {sizes['parquet']:,} bytes "
              f"of Parquet ({ratio:.1f}x smaller)")  # fmt: skip
    print(f"\nconvert and write took {record['seconds']['convert_and_write']}s")
    print(f"reconciliation record: s3://{settings.lake_bucket}/{record_key}")


if __name__ == "__main__":
    main()
