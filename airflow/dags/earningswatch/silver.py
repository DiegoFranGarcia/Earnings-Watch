"""Writing to the silver zone: typed Parquet that can always be rebuilt from bronze."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from earningswatch.daily_index import Filing


def write_filings(filings: list[Filing], path: Path) -> int:
    """Write daily-index filings as ZSTD Parquet with an explicit schema; return the row count."""
    import pyarrow as pa  # imported here, not at module level: DAG parsing stays fast
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            ("cik", pa.int64()),
            ("company_name", pa.string()),
            ("form_type", pa.string()),
            ("date_filed", pa.date32()),
            ("filename", pa.string()),
            ("accession_number", pa.string()),
        ]
    )
    columns = {name: [getattr(f, name) for f in filings] for name in schema.names}
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns, schema=schema), path, compression="zstd")
    return len(filings)


def replace_partition(s3: Any, bucket: str, local: Path, key: str) -> None:
    """Make `key`'s folder hold exactly this one file: delete what is there, then upload.

    Silver is derived from bronze, so replacing a partition is always safe, and reruns
    never leave duplicate files behind.
    """
    prefix = key.rsplit("/", 1)[0] + "/"
    for obj in s3.list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents", []):
        s3.delete_object(Bucket=bucket, Key=obj["Key"])
    s3.upload_file(str(local), bucket, key)
