"""The Financial Statement Data Sets' columns, and how each one is typed.

Every column is read as text first, then cast deliberately. Nothing is inferred: a guessed
type is a silent bug (codes such as fye, ein and zip codes would lose their leading zeros).
These match slice/fsds_to_parquet.py exactly, so Spark and DuckDB produce the same silver.
"""

from __future__ import annotations

SUB_COLUMNS = (
    "adsh", "cik", "name", "sic", "countryba", "stprba", "cityba", "zipba", "bas1", "bas2",
    "baph", "countryma", "stprma", "cityma", "zipma", "mas1", "mas2", "countryinc", "stprinc",
    "ein", "former", "changed", "afs", "wksi", "fye", "form", "period", "fy", "fp", "filed",
    "accepted", "prevrpt", "detail", "instance", "nciks", "aciks",
)  # fmt: skip
NUM_COLUMNS = (
    "adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg", "value", "footnote",
)  # fmt: skip
# The SEC's eight-column key for one reported number.
NUM_KEY = ("adsh", "tag", "version", "ddate", "qtrs", "uom", "segments", "coreg")
# Filing attributes copied onto every number, so later layers rarely need to join sub.
NUM_ENRICHMENT = ("cik", "form", "filed", "fy", "fp")

# Spark SQL expressions; {c} is the column. try_* returns null on a bad value instead of
# failing, because Spark 4 runs in ANSI mode, where a plain cast of bad text throws.
DATE = "to_date(try_to_timestamp({c}, 'yyyyMMdd'))"
INT = "try_cast({c} AS INT)"
BOOL = "CASE {c} WHEN '1' THEN TRUE WHEN '0' THEN FALSE END"

SUB_CASTS = {
    "cik": "try_cast({c} AS BIGINT)",
    "sic": INT,
    "changed": DATE,
    "wksi": BOOL,
    "period": DATE,
    "fy": INT,
    "filed": DATE,
    # The SEC gives no time zone (EDGAR runs on Eastern time), so it stays a plain timestamp.
    "accepted": "try_cast({c} AS TIMESTAMP_NTZ)",
    "prevrpt": BOOL,
    "detail": BOOL,
    "nciks": INT,
}
NUM_CASTS = {
    "ddate": DATE,
    "qtrs": INT,
    "value": "try_cast({c} AS DECIMAL(28, 4))",  # exactly as the SEC defines it
}
