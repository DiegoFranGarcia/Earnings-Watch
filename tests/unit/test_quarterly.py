"""Unit tests for landing a quarter and noticing republications. S3 is faked with moto."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from earningswatch import fsds
from earningswatch.bronze import Manifest, read_manifest
from earningswatch.quarterly import land_quarter, looks_changed, version_label
from earningswatch.sec_client import DownloadResult, RemoteFile

BUCKET = "lake"
BASE_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets"
TODAY = dt.date(2026, 11, 15)
ORIGINAL_DATE = "Thu, 01 Oct 2026 12:00:00 GMT"
REPUBLISHED_DATE = "Sun, 15 Nov 2026 09:30:00 GMT"


class FakeSec:
    """Serves one 'published' file; counts HEADs and downloads."""

    def __init__(self, body: bytes, last_modified: str) -> None:
        self.publish(body, last_modified)
        self.heads = 0
        self.downloads = 0

    def publish(self, body: bytes, last_modified: str) -> None:
        self.body, self.last_modified = body, last_modified

    def metadata(self, url: str) -> RemoteFile:
        self.heads += 1
        return RemoteFile(len(self.body), self.last_modified)

    def download(self, url: str, dest: Path) -> DownloadResult:
        self.downloads += 1
        dest.write_bytes(self.body)
        sha = hashlib.sha256(self.body).hexdigest()
        return DownloadResult(url, dest, len(self.body), sha, self.last_modified)


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def _land(sec, s3):
    return land_quarter(sec, s3, BUCKET, "2026q3", BASE_URL, TODAY)


def test_first_landing_goes_to_the_original_key(s3) -> None:
    sec = FakeSec(b"original zip", ORIGINAL_DATE)

    landing = _land(sec, s3)

    assert landing.zip_key == fsds.zip_key("2026q3")
    assert (landing.downloaded, landing.republished) == (True, False)
    assert sec.downloads == 1


def test_unchanged_file_is_not_downloaded_again(s3) -> None:
    sec = FakeSec(b"original zip", ORIGINAL_DATE)
    _land(sec, s3)

    again = _land(sec, s3)

    assert (again.downloaded, again.republished) == (False, False)
    assert sec.downloads == 1, "only a HEAD request, never a second download"
    assert sec.heads == 1


def test_republished_file_lands_beside_the_original(s3) -> None:
    sec = FakeSec(b"original zip", ORIGINAL_DATE)
    _land(sec, s3)
    sec.publish(b"republished zip, different bytes", REPUBLISHED_DATE)

    landing = _land(sec, s3)

    assert landing.republished is True
    assert landing.zip_key == fsds.version_zip_key("2026q3", "20261115")
    original = read_manifest(s3, BUCKET, fsds.zip_key("2026q3"))
    assert original.sha256 == hashlib.sha256(b"original zip").hexdigest(), "never overwritten"


def test_republication_is_recognised_on_later_runs(s3) -> None:
    sec = FakeSec(b"original zip", ORIGINAL_DATE)
    _land(sec, s3)
    sec.publish(b"republished zip, different bytes", REPUBLISHED_DATE)
    _land(sec, s3)

    later = _land(sec, s3)

    assert later.zip_key == fsds.version_zip_key("2026q3", "20261115")
    assert (later.downloaded, later.republished) == (False, True)
    assert sec.downloads == 2, "compared with the newest copy, so nothing is fetched again"


def test_new_date_but_identical_bytes_keeps_no_extra_copy(s3) -> None:
    sec = FakeSec(b"original zip", ORIGINAL_DATE)
    _land(sec, s3)
    sec.publish(b"original zip", REPUBLISHED_DATE)  # re-uploaded, content unchanged

    landing = _land(sec, s3)

    assert landing.zip_key == fsds.zip_key("2026q3")
    assert landing.republished is False
    listing = s3.list_objects_v2(Bucket=BUCKET, Prefix=fsds.bronze_prefix("2026q3") + "/version=")
    assert listing.get("KeyCount", 0) == 0


def test_looks_changed() -> None:
    held = Manifest("u", "s3://x", 100, "abc", ORIGINAL_DATE, "2026-10-02T00:00:00+00:00")
    assert looks_changed(held, RemoteFile(100, ORIGINAL_DATE)) is False
    assert looks_changed(held, RemoteFile(None, ORIGINAL_DATE)) is False  # unknown size
    assert looks_changed(held, RemoteFile(101, ORIGINAL_DATE)) is True
    assert looks_changed(held, RemoteFile(100, REPUBLISHED_DATE)) is True


def test_version_label() -> None:
    assert version_label(REPUBLISHED_DATE, TODAY) == "20261115"
    assert version_label(None, dt.date(2026, 12, 2)) == "20261202"
    assert version_label("not a date", dt.date(2026, 12, 2)) == "20261202"
