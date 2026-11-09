"""Pure DataFrame-to-DataFrame steps for turning FSDS text into silver.

Nothing here reads or writes storage, so each step is unit-tested on tiny inputs.
"""

from __future__ import annotations

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

from lib.schemas import NUM_COLUMNS, NUM_ENRICHMENT, NUM_KEY

CORRUPT = "_corrupt_record"


class HeaderMismatch(ValueError):
    """A source file's columns differ from the schema the job expects."""


def check_header(spark: SparkSession, path: str, columns: tuple[str, ...]) -> None:
    """Fail unless the file's header row is exactly `columns`, in order.

    Spark maps an explicit schema onto a CSV file by position and never compares the header's
    names. Without this check, a renamed or reordered column would load into the wrong field
    silently, and an added one would quarantine every row under a misleading message.
    """
    first = spark.read.text(path).first()  # reads only the start of the file
    found = tuple(first.value.rstrip("\r").split("\t")) if first else ()
    if found == tuple(columns):
        return
    added = [c for c in found if c not in columns]
    missing = [c for c in columns if c not in found]
    change = (
        "; ".join(
            part
            for part in (f"added {added}" if added else "", f"missing {missing}" if missing else "")
            if part
        )
        or "same columns in a different order"
    )
    raise HeaderMismatch(f"{path}: columns changed ({change}); expected {list(columns)}")


def read_raw(spark: SparkSession, path: str, columns: tuple[str, ...]) -> DataFrame:
    """Read a tab-separated FSDS file with every column as text.

    The SEC wraps fields containing tabs in double quotes, so quote handling stays on.
    A line with the wrong number of fields keeps its raw text in _corrupt_record.
    The result is cached: Spark refuses to filter on the corrupt-record column otherwise,
    and every row is used twice (good rows and quarantined rows).
    """
    schema = T.StructType(
        [T.StructField(c, T.StringType()) for c in columns]
        + [T.StructField(CORRUPT, T.StringType())]
    )
    return (
        spark.read.schema(schema)
        .option("sep", "\t")
        .option("header", True)
        .option("quote", '"')
        .option("escape", '"')
        .option("mode", "PERMISSIVE")
        .option("columnNameOfCorruptRecord", CORRUPT)
        .csv(path)
        .cache()
    )


def good_rows(raw: DataFrame) -> DataFrame:
    """Rows that parsed into the right number of fields."""
    return raw.filter(F.col(CORRUPT).isNull()).drop(CORRUPT)


def quarantined_rows(raw: DataFrame) -> DataFrame:
    """Lines that did not parse, as their raw text. Never silently dropped."""
    return raw.filter(F.col(CORRUPT).isNotNull()).select(F.col(CORRUPT).alias("raw_line"))


def _cast(column: str, casts: dict[str, str]) -> Column:
    if column in casts:
        return F.expr(casts[column].format(c=column)).alias(column)
    return F.col(column)


def typed(good: DataFrame, columns: tuple[str, ...], casts: dict[str, str]) -> DataFrame:
    """Cast each column deliberately; columns without a cast stay text."""
    return good.select(*[_cast(column, casts) for column in columns])


def count_cast_failures(good: DataFrame, casts: dict[str, str]) -> int:
    """Values that were present as text but did not survive their cast."""
    failures = [
        F.sum(
            F.when(F.col(column).isNotNull() & F.expr(expr.format(c=column)).isNull(), 1).otherwise(
                0
            )
        )
        for column, expr in casts.items()
    ]
    total = good.select(sum(failures, F.lit(0)).alias("failures")).first()["failures"]
    return int(total or 0)


def silver_num(num: DataFrame, sub: DataFrame) -> DataFrame:
    """Typed numbers, ready for silver.

    - exact duplicates (every column equal) are removed: they carry no new information;
    - rows sharing the eight-column key but reporting different values are all kept and
      flagged has_key_conflict, for dbt to decide on, instead of silently picking one;
    - filing attributes from sub are copied on, plus is_entity_total and period_type.
    """
    deduplicated = num.dropDuplicates(list(NUM_COLUMNS))
    filings = sub.select("adsh", *NUM_ENRICHMENT)
    key = Window.partitionBy(*NUM_KEY)
    return deduplicated.join(filings, on="adsh", how="left").select(
        *NUM_COLUMNS,
        *NUM_ENRICHMENT,
        (F.col("segments").isNull() & F.col("coreg").isNull()).alias("is_entity_total"),
        F.when(F.col("qtrs") == 0, "instant").otherwise("duration").alias("period_type"),
        (F.count(F.lit(1)).over(key) > 1).alias("has_key_conflict"),
    )
