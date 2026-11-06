"""Chaos drill: prove that a truncated ZIP is caught before it can reach later layers.

Runs two scenarios against the real bucket, in a scratch drills/ prefix that is always
deleted afterwards, using a copy of 2009q2's ZIP (bronze itself is only read):

1. Truncated at download: the server sends a short file and the download "succeeds",
   so its manifest records the short file's own checksum. Extraction must reject it.
2. Corrupted after landing: a complete, receipted ZIP is overwritten by a short copy.
   Extraction must reject it, because the bytes no longer match the manifest.

Run from the repository root:

    AWS_PROFILE=earnings-watch uv run python scripts/drill_truncated_zip.py
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "airflow" / "dags"))

import boto3  # noqa: E402 - after the path setup above

from earningswatch import fsds  # noqa: E402
from earningswatch.bronze import (  # noqa: E402
    BronzeIntegrityError,
    download_verified,
    extract_zip,
    land_file,
)
from earningswatch.sec_client import DownloadResult  # noqa: E402

SOURCE_QUARTER = "2009q2"
DRILL_PREFIX = "drills/truncated-zip"


class ServesBytes:
    """Stands in for SecClient: 'downloads' whatever bytes it was given."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    def download(self, url: str, dest: Path) -> DownloadResult:
        dest.write_bytes(self.body)
        sha = hashlib.sha256(self.body).hexdigest()
        return DownloadResult(url, dest, len(self.body), sha, None)


def _keys_under(s3, bucket: str, prefix: str) -> list[str]:
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    return [obj["Key"] for page in pages for obj in page.get("Contents", [])]


def _expect_rejected(s3, bucket: str, zip_key: str) -> str | None:
    """Run the real extraction; return the rejection message, or None if it wrongly passed."""
    try:
        extract_zip(s3, bucket, zip_key, fsds.FSDS_MEMBERS)
    except BronzeIntegrityError as exc:
        return str(exc)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", default=os.environ.get("LAKE_BUCKET"))
    args = parser.parse_args(argv)
    if not args.bucket:
        parser.error("give --bucket, or set LAKE_BUCKET")
    s3 = boto3.client("s3")
    bucket = args.bucket
    results: list[tuple[str, str | None, bool]] = []

    with tempfile.TemporaryDirectory(prefix="earningswatch-drill-") as tmp:
        local = Path(tmp) / "original.zip"
        download_verified(s3, bucket, fsds.zip_key(SOURCE_QUARTER), local)
        full = local.read_bytes()
    truncated = full[: len(full) // 2]
    print(f"Source: {fsds.zip_key(SOURCE_QUARTER)} ({len(full):,} bytes, verified)")
    print(f"Truncated copy: {len(truncated):,} bytes\n")

    try:
        # 1. Truncated at download: the short file gets landed with its own checksum.
        key1 = f"{DRILL_PREFIX}/at-download/{SOURCE_QUARTER}.zip"
        land_file(ServesBytes(truncated), s3, "drill://truncated", bucket, key1)
        message = _expect_rejected(s3, bucket, key1)
        nothing_extracted = all(
            not k.endswith(".txt") for k in _keys_under(s3, bucket, key1.rsplit("/", 1)[0])
        )
        results.append(("1. truncated at download", message, nothing_extracted))

        # 2. Corrupted after landing: a complete, receipted ZIP is overwritten by a short copy.
        key2 = f"{DRILL_PREFIX}/after-landing/{SOURCE_QUARTER}.zip"
        land_file(ServesBytes(full), s3, "drill://complete", bucket, key2)
        s3.put_object(Bucket=bucket, Key=key2, Body=truncated)
        message = _expect_rejected(s3, bucket, key2)
        nothing_extracted = all(
            not k.endswith(".txt") for k in _keys_under(s3, bucket, key2.rsplit("/", 1)[0])
        )
        results.append(("2. corrupted after landing", message, nothing_extracted))
    finally:
        leftovers = _keys_under(s3, bucket, DRILL_PREFIX + "/")
        for key in leftovers:
            s3.delete_object(Bucket=bucket, Key=key)
        print(f"Cleaned up {len(leftovers)} drill objects under {DRILL_PREFIX}/\n")

    caught_all = True
    for name, message, nothing_extracted in results:
        caught = message is not None and nothing_extracted
        caught_all &= caught
        print(f"{name}: {'CAUGHT' if caught else 'NOT CAUGHT'}")
        print(f"    rejected with: {message}")
        print(f"    files extracted from it: {'none' if nothing_extracted else 'SOME (bad)'}")
    print("\nDRILL PASSED" if caught_all and len(results) == 2 else "\nDRILL FAILED")
    return 0 if caught_all and len(results) == 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
