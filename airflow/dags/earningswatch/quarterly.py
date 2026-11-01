"""Landing a quarter's Financial Statement Data Set, and noticing when the SEC republishes one.

In December 2024 the SEC reprocessed every historical quarter. A pipeline that assumed
history never changes would silently keep stale copies. So each time a quarter is seen
again, its published size and date are compared with what bronze holds; a genuinely
different file is kept under a version= folder beside the original, and flagged for
reprocessing. Bronze is never overwritten.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

from earningswatch import fsds
from earningswatch.bronze import Manifest, land_file, land_new_version, read_manifest
from earningswatch.sec_client import RemoteFile, SecClient

_VERSION = re.compile(r"/version=([^/]+)/")


@dataclass(frozen=True)
class QuarterLanding:
    quarter: str
    zip_key: str  # the copy to extract and process: the newest one in bronze
    downloaded: bool
    republished: bool  # True when the newest copy is a republication


def version_label(last_modified: str | None, today: dt.date) -> str:
    """A folder label for a republished copy: the SEC's Last-Modified date, else today."""
    if last_modified:
        try:
            return f"{parsedate_to_datetime(last_modified):%Y%m%d}"
        except (TypeError, ValueError):
            pass
    return f"{today:%Y%m%d}"


def looks_changed(held: Manifest, remote: RemoteFile) -> bool:
    """Whether the published file's headers disagree with the copy in bronze."""
    if remote.size_bytes is not None and remote.size_bytes != held.size_bytes:
        return True
    return bool(
        remote.last_modified and held.last_modified and remote.last_modified != held.last_modified
    )


def newest_copy(s3: Any, bucket: str, quarter: str) -> tuple[str, Manifest] | None:
    """The newest complete copy of a quarter's ZIP: a version folder, else the original."""
    prefix = fsds.bronze_prefix(quarter) + "/version="
    labels = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            match = _VERSION.search(obj["Key"])
            if match and obj["Key"].endswith(".zip.manifest.json"):
                labels.add(match.group(1))
    for key in [fsds.version_zip_key(quarter, label) for label in sorted(labels, reverse=True)]:
        manifest = read_manifest(s3, bucket, key)
        if manifest is not None:
            return key, manifest
    original = fsds.zip_key(quarter)
    manifest = read_manifest(s3, bucket, original)
    return (original, manifest) if manifest is not None else None


def land_quarter(
    sec: SecClient, s3: Any, bucket: str, quarter: str, base_url: str, today: dt.date
) -> QuarterLanding:
    """Make sure bronze holds the SEC's current file for `quarter`. Safe to call repeatedly."""
    url = fsds.zip_url(quarter, base_url)
    newest = newest_copy(s3, bucket, quarter)
    if newest is None:
        land_file(sec, s3, url, bucket, fsds.zip_key(quarter))
        return QuarterLanding(quarter, fsds.zip_key(quarter), downloaded=True, republished=False)

    key, held = newest
    republished = key != fsds.zip_key(quarter)
    remote = sec.metadata(url)
    if remote is None or not looks_changed(held, remote):
        return QuarterLanding(quarter, key, downloaded=False, republished=republished)

    new_key = fsds.version_zip_key(quarter, version_label(remote.last_modified, today))
    landed = land_new_version(sec, s3, url, bucket, new_key, previous=held)
    if landed is None:  # new headers, same bytes: nothing to keep
        return QuarterLanding(quarter, key, downloaded=True, republished=republished)
    return QuarterLanding(quarter, new_key, downloaded=landed.downloaded, republished=True)
