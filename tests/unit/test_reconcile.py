"""Unit tests for reconciling bronze manifests against S3."""

from __future__ import annotations

import datetime as dt
import json

import boto3
import pytest
from moto import mock_aws

from earningswatch import daily_index, fsds
from earningswatch.reconcile import (
    StoredObject,
    business_days_between,
    load_bronze,
    quarters_between,
    reconcile,
    summarise,
)

WHEN = dt.datetime(2026, 11, 4, 22, 0, tzinfo=dt.UTC)
FRIDAY = dt.date(2026, 10, 23)


def _land(objects: dict, sizes: dict, key: str, size: int = 100) -> None:
    """Record one data file and its manifest, as land_file would leave them."""
    objects[key] = StoredObject(size, WHEN)
    objects[key + ".manifest.json"] = StoredObject(300, WHEN)
    sizes[key] = size


def _complete_quarter(objects: dict, sizes: dict, quarter: str) -> None:
    _land(objects, sizes, fsds.zip_key(quarter))
    for member in fsds.FSDS_MEMBERS:
        _land(objects, sizes, fsds.member_key(quarter, member))


def test_quarters_between() -> None:
    assert quarters_between("2009q2", "2010q1") == ["2009q2", "2009q3", "2009q4", "2010q1"]
    assert len(quarters_between("2009q2", "2026q3")) == 70


def test_business_days_between_skips_weekends_and_holidays() -> None:
    days = business_days_between(dt.date(2026, 11, 23), dt.date(2026, 11, 29))
    assert days == [dt.date(2026, 11, 23), dt.date(2026, 11, 24), dt.date(2026, 11, 25),
                    dt.date(2026, 11, 27)]  # fmt: skip  # Thanksgiving and the weekend skipped


def test_a_clean_bronze_reconciles() -> None:
    objects, sizes = {}, {}
    _complete_quarter(objects, sizes, "2026q3")
    _land(objects, sizes, daily_index.bronze_key(FRIDAY))

    report = reconcile(objects, sizes, ["2026q3"], [FRIDAY])

    assert report.integrity_ok
    assert (report.data_files, report.manifests) == (6, 6)
    assert report.files_by_source == {"daily_index": 1, "fsds": 5}
    assert report.missing_business_days == []
    assert report.newest_upload == WHEN


def test_a_file_without_a_manifest_is_a_problem() -> None:
    objects, sizes = {}, {}
    _complete_quarter(objects, sizes, "2026q3")
    objects["bronze/source=fsds/quarter=2026q3/half-uploaded.txt"] = StoredObject(5, WHEN)

    report = reconcile(objects, sizes, ["2026q3"], [])

    assert not report.integrity_ok
    assert report.files_without_manifest == ["bronze/source=fsds/quarter=2026q3/half-uploaded.txt"]


def test_a_size_mismatch_is_a_problem() -> None:
    objects, sizes = {}, {}
    _complete_quarter(objects, sizes, "2026q3")
    sizes[fsds.member_key("2026q3", "num.txt")] = 999  # the receipt disagrees with S3

    report = reconcile(objects, sizes, ["2026q3"], [])

    assert not report.integrity_ok
    assert "manifest says 999, S3 holds 100" in report.size_mismatches[0]


def test_an_orphaned_manifest_is_a_problem() -> None:
    objects, sizes = {}, {}
    _complete_quarter(objects, sizes, "2026q3")
    del objects[fsds.member_key("2026q3", "pre.txt")]  # the file vanished, its receipt did not

    report = reconcile(objects, sizes, ["2026q3"], [])

    assert report.manifests_without_file == [
        fsds.member_key("2026q3", "pre.txt") + ".manifest.json"
    ]
    assert report.incomplete_quarters == ["2026q3"]


def test_a_missing_quarter_is_incomplete() -> None:
    objects, sizes = {}, {}
    _complete_quarter(objects, sizes, "2026q3")

    report = reconcile(objects, sizes, ["2026q2", "2026q3"], [])

    assert report.incomplete_quarters == ["2026q2"]
    assert not report.integrity_ok


def test_a_missing_business_day_is_only_a_warning() -> None:
    objects, sizes = {}, {}
    monday = dt.date(2026, 10, 26)
    _land(objects, sizes, daily_index.bronze_key(FRIDAY))

    report = reconcile(objects, sizes, [], [FRIDAY, monday])

    assert report.missing_business_days == [monday]
    assert report.integrity_ok, "EDGAR may have published no index that day"
    assert any("2026-10-26 (Mon)" in line for line in summarise(report, "lake"))


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="lake")
        yield client


def test_load_bronze_reads_listing_and_manifests(s3) -> None:
    key = daily_index.bronze_key(FRIDAY)
    s3.put_object(Bucket="lake", Key=key, Body=b"x" * 42)
    s3.put_object(Bucket="lake", Key=key + ".manifest.json", Body=json.dumps({"size_bytes": 42}))
    s3.put_object(Bucket="lake", Key="silver/ignored.parquet", Body=b"not bronze")

    objects, sizes = load_bronze(s3, "lake")

    assert set(objects) == {key, key + ".manifest.json"}
    assert objects[key].size_bytes == 42
    assert sizes == {key: 42}
