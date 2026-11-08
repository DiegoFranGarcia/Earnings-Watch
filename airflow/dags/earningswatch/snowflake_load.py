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

from earningswatch.reconcile import quarters_between

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


def quarters_to_load(manual: str, announced: list[str]) -> list[str]:
    """A manual run's quarters ('2026q3', '2026q1,2026q3' or '2009q2..2026q3') if given,
    otherwise the quarters the triggering silver_fsds events announced. Sorted, no repeats."""
    quarters: list[str] = []
    for part in (p.strip().lower() for p in manual.split(",")):
        if ".." in part:
            first, last = (check_quarter(end.strip()) for end in part.split("..", 1))
            if first > last:
                raise ValueError(f"range runs backwards: {part!r}")
            quarters += quarters_between(first, last)
        elif part:
            quarters.append(check_quarter(part))
    if not manual.strip():
        quarters = [check_quarter(q) for q in announced]
    return sorted(set(quarters))


def connect(account: str, user: str, private_key_path: str, database: str, query_tag: str):
    """A Snowflake connection with key-pair login, defaulting to the RAW schema.

    The query tag labels every statement in Snowflake's query history, for cost attribution.
    """
    import os

    import snowflake.connector

    return snowflake.connector.connect(
        account=account,
        user=user,
        authenticator="SNOWFLAKE_JWT",
        private_key_file=os.path.expanduser(private_key_path),
        database=database,
        schema="RAW",
        session_parameters={"QUERY_TAG": query_tag},
    )


# -- the daily index: every filing EDGAR accepted, one file per business day ------------

_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

DAILY_INDEX_COLUMNS: tuple[tuple[str, str], ...] = (
    ("cik", "NUMBER(19,0)"),
    ("company_name", "VARCHAR"),
    ("form_type", "VARCHAR"),
    ("date_filed", "DATE"),
    ("filename", "VARCHAR"),
    ("accession_number", "VARCHAR"),
)

DAILY_INDEX_LINEAGE: tuple[tuple[str, str], ...] = (
    ("_source_file", "VARCHAR"),
    ("_source_date", "DATE"),
    ("_loaded_at", "TIMESTAMP_NTZ"),
)


def check_month(month: str) -> str:
    """Months are formatted into SQL patterns, so only exact labels like '2025-01' pass."""
    if not _MONTH.match(month):
        raise ValueError(f"not a month: {month!r}")
    return month


def months_between(first: str, last: str) -> list[str]:
    """'2025-11'..'2026-02' -> ['2025-11', '2025-12', '2026-01', '2026-02']."""
    year, month = map(int, check_month(first).split("-"))
    end = tuple(map(int, check_month(last).split("-")))
    if (year, month) > end:
        raise ValueError(f"range runs backwards: {first}..{last}")
    months = []
    while (year, month) <= end:
        months.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def daily_index_table_sql() -> str:
    body = ",\n    ".join(
        f"{name} {kind}" for name, kind in (*DAILY_INDEX_COLUMNS, *DAILY_INDEX_LINEAGE)
    )
    return f"CREATE TABLE IF NOT EXISTS RAW.DAILY_INDEX (\n    {body}\n)"


def daily_index_pattern(month: str) -> str:
    """Every day file of one month: silver/daily_index/date=YYYY-MM-DD/part-0.parquet."""
    return f".*date={check_month(month)}-[0-9]{{2}}/.*[.]parquet"


def daily_index_copy_sql(month: str, stage: str = "RAW.SILVER") -> str:
    targets = [name for name, _ in DAILY_INDEX_COLUMNS] + [n for n, _ in DAILY_INDEX_LINEAGE]
    values = [f'$1:"{name}"::{kind}' for name, kind in DAILY_INDEX_COLUMNS] + [
        "METADATA$FILENAME",
        # The day comes from the partition folder the file sits in.
        "to_date(regexp_substr(METADATA$FILENAME, 'date=([0-9]{4}-[0-9]{2}-[0-9]{2})', 1, 1, 'e'))",
        "CURRENT_TIMESTAMP()::TIMESTAMP_NTZ",
    ]
    # Not injectable: names are module constants and the month passed check_month().
    return (
        f"COPY INTO RAW.DAILY_INDEX ({', '.join(targets)})\n"  # noqa: S608
        f"FROM (SELECT {', '.join(values)}\n"
        f"      FROM @{stage}/daily_index/)\n"
        f"PATTERN = '{daily_index_pattern(month)}'\n"
        "FORCE = TRUE\n"
        "ON_ERROR = ABORT_STATEMENT"
    )


def load_daily_index_month(cursor, month: str, stage: str = "RAW.SILVER") -> int:
    """Replace one month of the daily index, committing only if RAW holds exactly the rows
    the month's silver files contain (counted by Snowflake from the files themselves)."""
    pattern = daily_index_pattern(month)
    first_day = f"{month}-01"
    where = "WHERE _source_date BETWEEN %s::date AND last_day(%s::date)"
    cursor.execute("BEGIN")
    try:
        cursor.execute(f"DELETE FROM RAW.DAILY_INDEX {where}", (first_day, first_day))  # noqa: S608
        cursor.execute(daily_index_copy_sql(month, stage))
        cursor.execute(f"SELECT COUNT(*) FROM RAW.DAILY_INDEX {where}", (first_day, first_day))  # noqa: S608
        loaded = int(cursor.fetchone()[0])
        cursor.execute(
            f"SELECT COUNT(*) FROM @{stage}/daily_index/ (PATTERN => %s)",  # noqa: S608
            (pattern,),
        )
        in_files = int(cursor.fetchone()[0])
        if loaded != in_files:
            raise LoadMismatch(f"{month}: RAW holds {loaded:,} rows, the files hold {in_files:,}")
    except BaseException:
        cursor.execute("ROLLBACK")
        raise
    cursor.execute("COMMIT")
    log.info("Loaded daily index %s: %s rows", month, f"{loaded:,}")
    return loaded


class SnowflakeSettingsMissing(RuntimeError):
    """Snowflake is not configured for this Airflow."""


def connect_from_settings(settings, query_tag: str):
    """A connection from the SF_* settings, naming any that are missing."""
    missing = [
        name
        for name, value in (
            ("SF_ACCOUNT", settings.sf_account),
            ("SF_USER", settings.sf_user),
            ("SF_PRIVATE_KEY_PATH", settings.sf_private_key_path),
            ("SF_DATABASE", settings.sf_database),
        )
        if not value
    ]
    if missing:
        raise SnowflakeSettingsMissing(f"set {', '.join(missing)} in airflow/.env")
    return connect(
        settings.sf_account,
        settings.sf_user,
        settings.sf_private_key_path,
        settings.sf_database,
        query_tag,
    )


def months_to_load(manual: str, announced_days: list[str]) -> list[str]:
    """A manual run's months ('2025-01' or '2025-01..2026-11') if given, otherwise the months
    of the days the triggering silver_daily_index events announced. Sorted, no repeats."""
    manual = manual.strip()
    if manual:
        first, _, last = manual.partition("..")
        return months_between(first.strip(), (last or first).strip())
    return sorted({check_month(day[:7]) for day in announced_days})
