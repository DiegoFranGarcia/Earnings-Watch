"""Reconciling bronze: do the receipts (manifests) agree with what is actually in S3?

Checks, from most to least serious:

- every data file has a manifest, and every manifest has its data file;
- every manifest's size matches the size of the object in S3;
- every expected FSDS quarter holds its ZIP and four members;
- every expected business day has its daily index.

The first three are integrity problems. A missing business day is reported as a
warning, because EDGAR occasionally publishes no index for a day (an unscheduled
closure), and the daily DAG deliberately skips such days.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from earningswatch import daily_index, fsds
from earningswatch.bronze import MANIFEST_SUFFIX

BRONZE_PREFIX = "bronze/"


@dataclass(frozen=True)
class StoredObject:
    size_bytes: int
    last_modified: dt.datetime


@dataclass
class Report:
    data_files: int = 0
    manifests: int = 0
    total_bytes: int = 0
    newest_upload: dt.datetime | None = None
    bytes_by_source: dict[str, int] = field(default_factory=dict)
    files_by_source: dict[str, int] = field(default_factory=dict)
    files_without_manifest: list[str] = field(default_factory=list)
    manifests_without_file: list[str] = field(default_factory=list)
    size_mismatches: list[str] = field(default_factory=list)
    quarters_expected: int = 0
    incomplete_quarters: list[str] = field(default_factory=list)
    business_days_expected: int = 0
    missing_business_days: list[dt.date] = field(default_factory=list)

    @property
    def integrity_ok(self) -> bool:
        return not (self.files_without_manifest or self.manifests_without_file or
                    self.size_mismatches or self.incomplete_quarters)  # fmt: skip


def quarters_between(first: str, last: str) -> list[str]:
    """Every quarter label from `first` to `last`, inclusive: '2009q2' ... '2026q3'."""
    year, quarter = int(first[:4]), int(first[5])
    end = (int(last[:4]), int(last[5]))
    labels = []
    while (year, quarter) <= end:
        labels.append(f"{year}q{quarter}")
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return labels


def business_days_between(first: dt.date, last: dt.date) -> list[dt.date]:
    days = (first + dt.timedelta(days=n) for n in range((last - first).days + 1))
    return [day for day in days if daily_index.is_business_day(day)]


def _source(key: str) -> str:
    """'bronze/source=fsds/...' -> 'fsds'."""
    part = key[len(BRONZE_PREFIX) :].split("/", 1)[0]
    return part.removeprefix("source=")


def reconcile(
    objects: dict[str, StoredObject],
    manifest_sizes: dict[str, int],
    quarters: list[str],
    business_days: list[dt.date],
) -> Report:
    """Compare S3's listing with the manifests' recorded sizes. Pure: no S3 calls here.

    `objects` maps every key under bronze/ to its size and upload time; `manifest_sizes`
    maps each data file's key to the size its manifest records.
    """
    report = Report(quarters_expected=len(quarters), business_days_expected=len(business_days))
    files_by_source: dict[str, int] = defaultdict(int)
    bytes_by_source: dict[str, int] = defaultdict(int)
    data_keys = set()

    for key, stored in objects.items():
        if report.newest_upload is None or stored.last_modified > report.newest_upload:
            report.newest_upload = stored.last_modified
        report.total_bytes += stored.size_bytes
        if key.endswith(MANIFEST_SUFFIX):
            report.manifests += 1
            if key.removesuffix(MANIFEST_SUFFIX) not in objects:
                report.manifests_without_file.append(key)
            continue
        report.data_files += 1
        data_keys.add(key)
        files_by_source[_source(key)] += 1
        bytes_by_source[_source(key)] += stored.size_bytes
        if key not in manifest_sizes:
            report.files_without_manifest.append(key)
        elif manifest_sizes[key] != stored.size_bytes:
            report.size_mismatches.append(
                f"{key}: manifest says {manifest_sizes[key]}, S3 holds {stored.size_bytes}"
            )

    complete = data_keys & set(manifest_sizes)
    for quarter in quarters:
        needed = [fsds.zip_key(quarter)] + [fsds.member_key(quarter, m) for m in fsds.FSDS_MEMBERS]
        if not all(key in complete for key in needed):
            report.incomplete_quarters.append(quarter)
    report.missing_business_days = [
        day for day in business_days if daily_index.bronze_key(day) not in complete
    ]
    report.files_by_source = dict(sorted(files_by_source.items()))
    report.bytes_by_source = dict(sorted(bytes_by_source.items()))
    for problems in (report.files_without_manifest, report.manifests_without_file,
                     report.size_mismatches):  # fmt: skip
        problems.sort()
    return report


def load_bronze(s3: Any, bucket: str) -> tuple[dict[str, StoredObject], dict[str, int]]:
    """List everything under bronze/ and read every manifest's recorded size."""
    objects: dict[str, StoredObject] = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=BRONZE_PREFIX):
        for obj in page.get("Contents", []):
            objects[obj["Key"]] = StoredObject(obj["Size"], obj["LastModified"])
    manifest_sizes = {}
    for key in objects:
        if key.endswith(MANIFEST_SUFFIX):
            body = json.loads(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
            manifest_sizes[key.removesuffix(MANIFEST_SUFFIX)] = int(body["size_bytes"])
    return objects, manifest_sizes


def summarise(report: Report, bucket: str) -> list[str]:
    """Human-readable lines for the terminal."""
    gb = 1024**3
    lines = [
        f"Bronze reconciliation for s3://{bucket}/{BRONZE_PREFIX}",
        f"  data files: {report.data_files:,}   manifests: {report.manifests:,}   "
        f"total: {report.total_bytes / gb:,.2f} GB",
        f"  newest upload: {report.newest_upload:%Y-%m-%d %H:%M:%S %Z}"
        if report.newest_upload
        else "  newest upload: (bronze is empty)",
    ]
    for source, count in report.files_by_source.items():
        size = report.bytes_by_source[source] / gb
        lines.append(f"    {source:<16} {count:>6,} files  {size:>8,.2f} GB")
    lines.append(
        f"  integrity: {len(report.files_without_manifest)} files without a manifest, "
        f"{len(report.manifests_without_file)} manifests without a file, "
        f"{len(report.size_mismatches)} size mismatches"
    )
    for problem in (report.files_without_manifest + report.manifests_without_file +
                    report.size_mismatches)[:20]:  # fmt: skip
        lines.append(f"    ! {problem}")
    complete = report.quarters_expected - len(report.incomplete_quarters)
    lines.append(f"  FSDS quarters complete: {complete}/{report.quarters_expected}")
    if report.incomplete_quarters:
        lines.append(f"    ! incomplete: {', '.join(report.incomplete_quarters)}")
    present = report.business_days_expected - len(report.missing_business_days)
    lines.append(f"  daily index days present: {present}/{report.business_days_expected}")
    if report.missing_business_days:
        days = ", ".join(f"{d:%Y-%m-%d (%a)}" for d in report.missing_business_days)
        lines.append(f"    ? missing (warning: check whether EDGAR published them): {days}")
    lines.append("RESULT: OK" if report.integrity_ok else "RESULT: PROBLEMS FOUND")
    return lines
