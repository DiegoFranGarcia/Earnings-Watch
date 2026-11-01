"""Writing to the silver zone: typed Parquet that can always be rebuilt from bronze."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from earningswatch.company_tickers import TickerListing
from earningswatch.daily_index import Filing

FILING_COLUMNS = (
    ("cik", "int64"),
    ("company_name", "string"),
    ("form_type", "string"),
    ("date_filed", "date32"),
    ("filename", "string"),
    ("accession_number", "string"),
)
TICKER_COLUMNS = (
    ("cik", "int64"),
    ("name", "string"),
    ("ticker", "string"),
    ("exchange", "string"),
)


def write_records(records: Sequence[Any], columns: Sequence[tuple[str, str]], path: Path) -> int:
    """Write dataclass records as ZSTD Parquet with an explicit schema; return the row count.

    The schema is declared, never inferred, so even an empty day writes a correctly typed file.
    """
    import pyarrow as pa  # imported here, not at module level: DAG parsing stays fast
    import pyarrow.parquet as pq

    schema = pa.schema([(name, pa.type_for_alias(type_name)) for name, type_name in columns])
    data = {name: [getattr(record, name) for record in records] for name, _ in columns}
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(data, schema=schema), path, compression="zstd")
    return len(records)


def write_filings(filings: list[Filing], path: Path) -> int:
    return write_records(filings, FILING_COLUMNS, path)


def write_tickers(listings: list[TickerListing], path: Path) -> int:
    return write_records(listings, TICKER_COLUMNS, path)


def replace_partition(s3: Any, bucket: str, local: Path, key: str) -> None:
    """Make `key`'s folder hold exactly this one file: delete what is there, then upload.

    Silver is derived from bronze, so replacing a partition is always safe, and reruns
    never leave duplicate files behind.
    """
    prefix = key.rsplit("/", 1)[0] + "/"
    for obj in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.upload_file(str(local), bucket, key)
