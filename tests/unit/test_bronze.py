"""Unit tests for landing files in bronze. S3 is faked with moto; no AWS calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from earningswatch.bronze import land_file, manifest_key, read_manifest
from earningswatch.sec_client import DownloadResult

BUCKET = "earnings-watch-test"
URL = "https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/master.20261023.idx"
KEY = "bronze/source=daily_index/date=2026-10-23/master.20261023.idx"
BODY = b"CIK|Company Name|Form Type|Date Filed|Filename\n" * 500


class FakeSec:
    """Stands in for SecClient: 'downloads' fixed bytes and counts the downloads."""

    def __init__(self, body: bytes = BODY) -> None:
        self.body = body
        self.downloads = 0

    def download(self, url: str, dest: Path) -> DownloadResult:
        self.downloads += 1
        dest.write_bytes(self.body)
        return DownloadResult(
            url=url,
            path=dest,
            size_bytes=len(self.body),
            sha256=hashlib.sha256(self.body).hexdigest(),
            last_modified="Fri, 23 Oct 2026 22:15:00 GMT",
        )


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch):
    # Fake credentials, so a test can never touch your real AWS account.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_lands_file_and_manifest(s3) -> None:
    result = land_file(FakeSec(), s3, URL, BUCKET, KEY)

    assert result.downloaded is True
    landed = s3.get_object(Bucket=BUCKET, Key=KEY)
    assert landed["Body"].read() == BODY
    assert landed["Metadata"]["sha256"] == hashlib.sha256(BODY).hexdigest()

    manifest = json.loads(s3.get_object(Bucket=BUCKET, Key=manifest_key(KEY))["Body"].read())
    assert manifest["source_url"] == URL
    assert manifest["s3_uri"] == f"s3://{BUCKET}/{KEY}"
    assert manifest["size_bytes"] == len(BODY)
    assert manifest["sha256"] == hashlib.sha256(BODY).hexdigest()


def test_second_run_downloads_nothing(s3) -> None:
    sec = FakeSec()

    first = land_file(sec, s3, URL, BUCKET, KEY)
    second = land_file(sec, s3, URL, BUCKET, KEY)

    assert sec.downloads == 1, "a landed file must never be downloaded again"
    assert second.downloaded is False
    assert second.manifest == first.manifest


def test_file_without_manifest_is_replaced(s3) -> None:
    # An earlier run uploaded half a file, then died before writing the manifest.
    s3.put_object(Bucket=BUCKET, Key=KEY, Body=b"half a fi")

    result = land_file(FakeSec(), s3, URL, BUCKET, KEY)

    assert result.downloaded is True
    assert s3.get_object(Bucket=BUCKET, Key=KEY)["Body"].read() == BODY


def test_failed_download_lands_nothing(s3) -> None:
    class BrokenSec(FakeSec):
        def download(self, url: str, dest: Path) -> DownloadResult:
            raise ConnectionError("SEC unreachable")

    with pytest.raises(ConnectionError):
        land_file(BrokenSec(), s3, URL, BUCKET, KEY)

    assert read_manifest(s3, BUCKET, KEY) is None
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0
