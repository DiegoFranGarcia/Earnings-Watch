"""Landing SEC files in the bronze zone of the lake.

Bronze holds files exactly as the SEC published them. Each file gets a
manifest beside it, and the manifest is written last, so it doubles as a
commit marker:

- file and manifest both present: the file is complete and final, and is
  never downloaded or extracted again;
- file present but no manifest: an earlier run died halfway, so the file is
  incomplete and gets replaced.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from earningswatch.sec_client import SecClient

log = logging.getLogger(__name__)

MANIFEST_SUFFIX = ".manifest.json"
CHUNK_SIZE = 1024 * 1024  # 1 MiB


class BronzeIntegrityError(RuntimeError):
    """What is in bronze does not match what was expected."""


@dataclass(frozen=True)
class Manifest:
    source_url: str
    s3_uri: str
    size_bytes: int
    sha256: str
    last_modified: str | None
    downloaded_at: str
    line_count: int | None = None  # set for text files extracted from a ZIP


@dataclass(frozen=True)
class LandResult:
    manifest: Manifest
    downloaded: bool  # False when the file was already complete in bronze


@dataclass(frozen=True)
class ExtractResult:
    member: str
    manifest: Manifest
    extracted: bool  # False when the member was already complete in bronze


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
        manifest = _upload_and_commit(
            s3,
            bucket,
            key,
            result.path,
            source_url=url,
            sha256=result.sha256,
            size_bytes=result.size_bytes,
            last_modified=result.last_modified,
        )
    return LandResult(manifest, downloaded=True)


def extract_zip(
    s3: Any, bucket: str, zip_key: str, members: tuple[str, ...]
) -> list[ExtractResult]:
    """Extract `members` of a landed ZIP into the same bronze folder, once each.

    The ZIP must already be landed (have a manifest), and its checksum must
    still match that manifest. A corrupt or truncated ZIP is rejected.
    """
    zip_manifest = read_manifest(s3, bucket, zip_key)
    if zip_manifest is None:
        raise BronzeIntegrityError(f"s3://{bucket}/{zip_key} has not been landed completely")

    folder = zip_key.rsplit("/", 1)[0]
    keys = {member: f"{folder}/{member}" for member in members}
    existing = {member: read_manifest(s3, bucket, key) for member, key in keys.items()}
    todo = [member for member in members if existing[member] is None]

    results = {
        member: ExtractResult(member, manifest, extracted=False)
        for member, manifest in existing.items()
        if manifest is not None
    }
    if todo:
        with tempfile.TemporaryDirectory(prefix="earningswatch-") as tmp:
            local_zip = Path(tmp) / Path(zip_key).name
            s3.download_file(bucket, zip_key, str(local_zip))
            if _sha256_of(local_zip) != zip_manifest.sha256:
                raise BronzeIntegrityError(
                    f"s3://{bucket}/{zip_key} no longer matches its manifest checksum"
                )
            try:
                with zipfile.ZipFile(local_zip) as archive:
                    _check_archive(archive, zip_key, todo)
                    for member in todo:
                        manifest = _extract_member(
                            s3, bucket, archive, member, keys[member], zip_key, Path(tmp)
                        )
                        results[member] = ExtractResult(member, manifest, extracted=True)
            except zipfile.BadZipFile as exc:
                raise BronzeIntegrityError(f"s3://{bucket}/{zip_key} is not a valid ZIP") from exc

    return [results[member] for member in members]


def download_verified(s3: Any, bucket: str, key: str, dest: Path) -> Manifest:
    """Copy a landed bronze file to `dest`, proving it matches its manifest checksum.

    A local copy that already matches is reused, so repeated runs download nothing.
    """
    manifest = read_manifest(s3, bucket, key)
    if manifest is None:
        raise BronzeIntegrityError(f"s3://{bucket}/{key} has not been landed completely")
    if (
        dest.exists()
        and dest.stat().st_size == manifest.size_bytes
        and _sha256_of(dest) == manifest.sha256
    ):
        log.info("Local copy already verified: %s", dest)
        return manifest

    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".part")
    s3.download_file(bucket, key, str(partial))
    if _sha256_of(partial) != manifest.sha256:
        partial.unlink()
        raise BronzeIntegrityError(f"s3://{bucket}/{key} does not match its manifest checksum")
    partial.replace(dest)  # only a verified file ever appears under the real name
    log.info("Downloaded and verified %s", dest)
    return manifest


# -- internals ----------------------------------------------------------------


def _check_archive(archive: zipfile.ZipFile, zip_key: str, wanted: list[str]) -> None:
    corrupt = archive.testzip()  # reads every member and checks its CRC
    if corrupt is not None:
        raise BronzeIntegrityError(f"{zip_key}: member {corrupt} is corrupt")
    names = set(archive.namelist())
    missing = [member for member in wanted if member not in names]
    if missing:
        raise BronzeIntegrityError(f"{zip_key} has no {missing}; it contains {sorted(names)}")


def _extract_member(
    s3: Any,
    bucket: str,
    archive: zipfile.ZipFile,
    member: str,
    key: str,
    zip_key: str,
    workdir: Path,
) -> Manifest:
    local = workdir / member
    digest = hashlib.sha256()
    size = 0
    lines = 0
    with archive.open(member) as src, local.open("wb") as dst:
        while chunk := src.read(CHUNK_SIZE):
            dst.write(chunk)
            digest.update(chunk)
            size += len(chunk)
            lines += chunk.count(b"\n")
    manifest = _upload_and_commit(
        s3,
        bucket,
        key,
        local,
        source_url=f"s3://{bucket}/{zip_key}#{member}",
        sha256=digest.hexdigest(),
        size_bytes=size,
        last_modified=None,
        line_count=lines,
    )
    local.unlink()  # free disk space before the next member
    return manifest


def _upload_and_commit(
    s3: Any,
    bucket: str,
    key: str,
    path: Path,
    *,
    source_url: str,
    sha256: str,
    size_bytes: int,
    last_modified: str | None,
    line_count: int | None = None,
) -> Manifest:
    """Upload a file, check what landed, then write its manifest last."""
    s3.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={"Metadata": {"sha256": sha256, "source-url": source_url}},
    )
    landed_size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
    if landed_size != size_bytes:
        raise BronzeIntegrityError(
            f"s3://{bucket}/{key} has {landed_size} bytes, expected {size_bytes}"
        )
    manifest = Manifest(
        source_url=source_url,
        s3_uri=f"s3://{bucket}/{key}",
        size_bytes=size_bytes,
        sha256=sha256,
        last_modified=last_modified,
        downloaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        line_count=line_count,
    )
    s3.put_object(
        Bucket=bucket,
        Key=manifest_key(key),
        Body=json.dumps(asdict(manifest), indent=2).encode(),
        ContentType="application/json",
    )
    log.info("Landed %s bytes at s3://%s/%s", size_bytes, bucket, key)
    return manifest


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
