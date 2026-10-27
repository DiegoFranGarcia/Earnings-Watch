"""Landing SEC files in the bronze zone of the lake.

Bronze holds files exactly as the SEC published them. Each file gets a
manifest beside it, and the manifest is written last, so it doubles as a
commit marker:

- file and manifest both present: the file is complete and final, and is
  never downloaded again;
- file present but no manifest: an earlier run died halfway, so the file is
  incomplete and gets replaced.
"""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from earningswatch.sec_client import SecClient

log = logging.getLogger(__name__)

MANIFEST_SUFFIX = ".manifest.json"


class BronzeIntegrityError(RuntimeError):
    """What landed in S3 does not match what was downloaded."""


@dataclass(frozen=True)
class Manifest:
    source_url: str
    s3_uri: str
    size_bytes: int
    sha256: str
    last_modified: str | None
    downloaded_at: str


@dataclass(frozen=True)
class LandResult:
    manifest: Manifest
    downloaded: bool  # False when the file was already complete in bronze


def manifest_key(key: str) -> str:
    return key + MANIFEST_SUFFIX


def read_manifest(s3: Any, bucket: str, key: str) -> Manifest | None:
    """The manifest for `key`, or None if the file has not been landed completely."""
    try:
        obj = s3.get_object(Bucket=bucket, Key=manifest_key(key))
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return Manifest(**json.loads(obj["Body"].read()))


def land_file(sec: SecClient, s3: Any, url: str, bucket: str, key: str) -> LandResult:
    """Download `url` into s3://bucket/key once. Safe to call any number of times."""
    existing = read_manifest(s3, bucket, key)
    if existing is not None:
        log.info("Already in bronze, not downloading again: s3://%s/%s", bucket, key)
        return LandResult(existing, downloaded=False)

    with tempfile.TemporaryDirectory(prefix="earningswatch-") as tmp:
        result = sec.download(url, Path(tmp) / Path(key).name)
        s3.upload_file(
            str(result.path),
            bucket,
            key,
            ExtraArgs={"Metadata": {"sha256": result.sha256, "source-url": url}},
        )

    landed_size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
    if landed_size != result.size_bytes:
        raise BronzeIntegrityError(
            f"s3://{bucket}/{key} has {landed_size} bytes, expected {result.size_bytes}"
        )

    manifest = Manifest(
        source_url=url,
        s3_uri=f"s3://{bucket}/{key}",
        size_bytes=result.size_bytes,
        sha256=result.sha256,
        last_modified=result.last_modified,
        downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    s3.put_object(
        Bucket=bucket,
        Key=manifest_key(key),
        Body=json.dumps(asdict(manifest), indent=2).encode(),
        ContentType="application/json",
    )
    log.info("Landed %s bytes at s3://%s/%s", result.size_bytes, bucket, key)
    return LandResult(manifest, downloaded=True)
