"""Load silver FSDS Parquet into Snowflake RAW tables, one quarter per transaction.

For each quarter, in one transaction: delete its rows, COPY INTO from its silver partition
with FORCE = TRUE, count the rows the transaction now holds, and commit only if the counts
equal Spark's reconciliation record. Any mismatch rolls back, leaving RAW as it was.

FORCE matters: COPY remembers which files it has loaded and silently skips them, so without
it, reloading a quarter would delete its rows and load nothing, without any error.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

_QUARTER = re.compile(r"^\d{4}q[1-4]$")

# Column types follow the silver Parquet Spark writes (checked against real output).
SUB_COLUMNS: tuple[tuple[str, str], ...] = (
    ("adsh", "VARCHAR"),
    ("cik", "NUMBER(19,0)"),
    ("name", "VARCHAR"),
    ("sic", "NUMBER(10,0)"),
    ("countryba", "VARCHAR"),
    ("stprba", "VARCHAR"),
    ("cityba", "VARCHAR"),
    ("zipba", "VARCHAR"),
    ("bas1", "VARCHAR"),
    ("bas2", "VARCHAR"),
    ("baph", "VARCHAR"),
    ("countryma", "VARCHAR"),
    ("stprma", "VARCHAR"),
    ("cityma", "VARCHAR"),
    ("zipma", "VARCHAR"),
    ("mas1", "VARCHAR"),
    ("mas2", "VARCHAR"),
    ("countryinc", "VARCHAR"),
    ("stprinc", "VARCHAR"),
    ("ein", "VARCHAR"),
    ("former", "VARCHAR"),
    ("changed", "DATE"),
    ("afs", "VARCHAR"),
    ("wksi", "BOOLEAN"),
    ("fye", "VARCHAR"),
    ("form", "VARCHAR"),
    ("period", "DATE"),
    ("fy", "NUMBER(10,0)"),
    ("fp", "VARCHAR"),
    ("filed", "DATE"),
    ("accepted", "TIMESTAMP_NTZ"),
    ("prevrpt", "BOOLEAN"),
    ("detail", "BOOLEAN"),
    ("instance", "VARCHAR"),
    ("nciks", "NUMBER(10,0)"),
    ("aciks", "VARCHAR"),
)

NUM_COLUMNS: tuple[tuple[str, str], ...] = (
    ("adsh", "VARCHAR"),
    ("tag", "VARCHAR"),
    ("version", "VARCHAR"),
    ("ddate", "DATE"),
    ("qtrs", "NUMBER(10,0)"),
    ("uom", "VARCHAR"),
    ("segments", "VARCHAR"),
    ("coreg", "VARCHAR"),
    ("value", "NUMBER(28,4)"),
    ("footnote", "VARCHAR"),
    ("cik", "NUMBER(19,0)"),
    ("form", "VARCHAR"),
    ("filed", "DATE"),
    ("fy", "NUMBER(10,0)"),
    ("fp", "VARCHAR"),
    ("is_entity_total", "BOOLEAN"),
    ("period_type", "VARCHAR"),
    ("has_key_conflict", "BOOLEAN"),
)

# Where every row came from, and when it arrived.
LINEAGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("_source_file", "VARCHAR"),
    ("_source_quarter", "VARCHAR"),
    ("_loaded_at", "TIMESTAMP_NTZ"),
)

# silver table -> (RAW table, its columns)
TABLES: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "sub": ("FSDS_SUB", SUB_COLUMNS),
    "num": ("FSDS_NUM", NUM_COLUMNS),
}


class LoadMismatch(RuntimeError):
    """RAW would not hold exactly the rows Spark wrote; the transaction was rolled back."""


@dataclass(frozen=True)
class QuarterLoad:
    quarter: str
    rows: dict[str, int]  # silver table -> rows now in RAW for this quarter


def check_quarter(quarter: str) -> str:
    """Quarters are formatted into SQL, so only exact labels like '2026q3' are accepted."""
    if not _QUARTER.match(quarter):
        raise ValueError(f"not a quarter: {quarter!r}")
    return quarter


def create_table_sql(table: str, columns: tuple[tuple[str, str], ...]) -> str:
    body = ",\n    ".join(f"{name} {kind}" for name, kind in (*columns, *LINEAGE_COLUMNS))
    return f"CREATE TABLE IF NOT EXISTS RAW.{table} (\n    {body}\n)"


def copy_sql(silver_table: str, quarter: str, stage: str = "RAW.SILVER") -> str:
    """COPY one quarter's silver partition into its RAW table, columns named explicitly."""
    check_quarter(quarter)
    table, columns = TABLES[silver_table]
    targets = [name for name, _ in columns] + [name for name, _ in LINEAGE_COLUMNS]
    values = [f'$1:"{name}"::{kind}' for name, kind in columns] + [
        "METADATA$FILENAME",
        f"'{quarter}'",
        "CURRENT_TIMESTAMP()::TIMESTAMP_NTZ",
    ]
    # Not injectable: table and column names are module constants, the quarter passed
    # check_quarter() (exactly "YYYYqN"), and a stage path cannot take a bound parameter.
    return (
        f"COPY INTO RAW.{table} ({', '.join(targets)})\n"  # noqa: S608
        f"FROM (SELECT {', '.join(values)}\n"
        f"      FROM @{stage}/fsds/{silver_table}/source_quarter={quarter}/)\n"
        "PATTERN = '.*[.]parquet'\n"
        "FORCE = TRUE\n"
        "ON_ERROR = ABORT_STATEMENT"
    )


def expected_rows(s3, bucket: str, quarter: str) -> dict[str, int]:
    """Rows Spark wrote for the quarter, from its reconciliation record in silver."""
    prefix = f"silver/_reconciliation/fsds/source_quarter={check_quarter(quarter)}/"
    keys = [
        o["Key"]
        for o in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", [])
        if o["Key"].rsplit("/", 1)[-1].startswith("part-")
    ]
    if len(keys) != 1:
        raise LoadMismatch(f"{prefix}: expected one reconciliation record, found {len(keys)}")
    record = json.loads(s3.get_object(Bucket=bucket, Key=keys[0])["Body"].read())
    return {t: int(record[t]["rows_written"]) for t in TABLES}


def load_quarter(cursor, quarter: str, expected: dict[str, int]) -> QuarterLoad:
    """Replace one quarter in RAW, committing only if every count matches `expected`."""
    check_quarter(quarter)
    cursor.execute("BEGIN")
    try:
        rows: dict[str, int] = {}
        for silver_table, (table, _) in TABLES.items():
            # Table names are constants from TABLES; the quarter is a bound parameter.
            where = "WHERE _source_quarter = %s"
            cursor.execute(f"DELETE FROM RAW.{table} {where}", (quarter,))  # noqa: S608
            cursor.execute(copy_sql(silver_table, quarter))
            cursor.execute(f"SELECT COUNT(*) FROM RAW.{table} {where}", (quarter,))  # noqa: S608
            rows[silver_table] = int(cursor.fetchone()[0])
        wrong = {t: (rows[t], expected[t]) for t in TABLES if rows[t] != expected[t]}
        if wrong:
            raise LoadMismatch(
                f"{quarter}: "
                + "; ".join(
                    f"{t} has {got:,} rows, Spark wrote {want:,}"
                    for t, (got, want) in wrong.items()
                )
            )
    except BaseException:
        cursor.execute("ROLLBACK")
        raise
    cursor.execute("COMMIT")
    log.info("Loaded %s: %s", quarter, ", ".join(f"{t} {n:,}" for t, n in rows.items()))
    return QuarterLoad(quarter, rows)
