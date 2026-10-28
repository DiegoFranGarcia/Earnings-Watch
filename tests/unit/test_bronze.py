"""Unit tests for landing files in bronze. S3 is faked with moto; no AWS calls."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from earningswatch.bronze import (
    BronzeIntegrityError,
    download_verified,
    extract_zip,
    land_file,
    manifest_key,
    read_manifest,
)
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


# -- extracting ZIPs ------------------------------------------------------------

ZIP_KEY = "bronze/source=fsds/quarter=2026q3/2026q3.zip"
MEMBERS = {
    "sub.txt": b"adsh\tcik\tname\n0000000001-26-000001\t1\tACME CORP\n",
    "num.txt": b"adsh\ttag\tvalue\n" + b"0000000001-26-000001\tNetIncomeLoss\t42\n" * 3,
}


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _land_zip(s3, body: bytes) -> None:
    land_file(FakeSec(body), s3, "https://www.sec.gov/fsds/2026q3.zip", BUCKET, ZIP_KEY)


def test_extracts_members_with_manifests(s3) -> None:
    _land_zip(s3, _zip_bytes(MEMBERS))

    results = extract_zip(s3, BUCKET, ZIP_KEY, ("sub.txt", "num.txt"))

    assert [r.member for r in results] == ["sub.txt", "num.txt"]
    assert all(r.extracted for r in results)
    folder = ZIP_KEY.rsplit("/", 1)[0]
    for name, data in MEMBERS.items():
        assert s3.get_object(Bucket=BUCKET, Key=f"{folder}/{name}")["Body"].read() == data
    num = results[1].manifest
    assert num.sha256 == hashlib.sha256(MEMBERS["num.txt"]).hexdigest()
    assert num.line_count == 4  # a header and three rows
    assert num.source_url.endswith("2026q3.zip#num.txt")


def test_second_extract_does_nothing(s3) -> None:
    _land_zip(s3, _zip_bytes(MEMBERS))

    first = extract_zip(s3, BUCKET, ZIP_KEY, ("sub.txt", "num.txt"))
    second = extract_zip(s3, BUCKET, ZIP_KEY, ("sub.txt", "num.txt"))

    assert not any(r.extracted for r in second)
    assert [r.manifest for r in second] == [r.manifest for r in first]


def test_refuses_a_zip_that_was_never_landed(s3) -> None:
    s3.put_object(Bucket=BUCKET, Key=ZIP_KEY, Body=_zip_bytes(MEMBERS))  # no manifest

    with pytest.raises(BronzeIntegrityError, match="not been landed"):
        extract_zip(s3, BUCKET, ZIP_KEY, ("sub.txt",))


def test_rejects_a_truncated_zip(s3) -> None:
    whole = _zip_bytes(MEMBERS)
    _land_zip(s3, whole[: len(whole) // 2])  # half a ZIP, cut off mid-file

    with pytest.raises(BronzeIntegrityError):
        extract_zip(s3, BUCKET, ZIP_KEY, ("sub.txt",))
    assert read_manifest(s3, BUCKET, ZIP_KEY.replace("2026q3.zip", "sub.txt")) is None


def test_rejects_a_missing_member(s3) -> None:
    _land_zip(s3, _zip_bytes(MEMBERS))

    with pytest.raises(BronzeIntegrityError, match="pre.txt"):
        extract_zip(s3, BUCKET, ZIP_KEY, ("sub.txt", "pre.txt"))


def test_rejects_a_zip_changed_since_landing(s3) -> None:
    _land_zip(s3, _zip_bytes(MEMBERS))
    s3.put_object(Bucket=BUCKET, Key=ZIP_KEY, Body=_zip_bytes({"sub.txt": b"tampered\n"}))

    with pytest.raises(BronzeIntegrityError, match="checksum"):
        extract_zip(s3, BUCKET, ZIP_KEY, ("sub.txt",))


# -- local verified copies --------------------------------------------------------


def test_download_verified_copies_and_reuses(s3, tmp_path) -> None:
    land_file(FakeSec(), s3, URL, BUCKET, KEY)
    dest = tmp_path / "copy" / "master.idx"

    download_verified(s3, BUCKET, KEY, dest)
    assert dest.read_bytes() == BODY

    s3.delete_object(Bucket=BUCKET, Key=KEY)  # if it tried to download again, this would fail
    download_verified(s3, BUCKET, KEY, dest)
    assert dest.read_bytes() == BODY


def test_download_verified_rejects_a_changed_file(s3, tmp_path) -> None:
    land_file(FakeSec(), s3, URL, BUCKET, KEY)
    s3.put_object(Bucket=BUCKET, Key=KEY, Body=b"not what was landed")
    dest = tmp_path / "master.idx"

    with pytest.raises(BronzeIntegrityError, match="checksum"):
        download_verified(s3, BUCKET, KEY, dest)
    assert not dest.exists()
    assert not dest.with_name(dest.name + ".part").exists()
