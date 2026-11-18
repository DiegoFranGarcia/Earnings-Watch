"""Unit tests for the site's export. S3 and Secrets Manager are faked with moto; no AWS calls."""

from __future__ import annotations

import datetime
import hashlib
import json

import boto3
import pytest
from moto import mock_aws

from earningswatch import site_export
from earningswatch.site_export import (
    POINTER_KEY,
    DispatchFailed,
    ExportTooLarge,
    dispatch_site_workflow,
    publish,
    read_token,
    run_folder,
)

BUCKET = "earnings-watch-test"
NOW = datetime.datetime(2026, 11, 19, 6, 30, tzinfo=datetime.UTC)


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch):
    # Fake credentials, so a test can never touch your real AWS account.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield s3, boto3.client("secretsmanager", region_name="us-east-1")


@pytest.fixture
def docs(tmp_path):
    path = tmp_path / "dbt-docs.html"
    path.write_text("<html>the dbt docs</html>")
    return path


def test_run_folders_are_safe_s3_keys() -> None:
    assert run_folder("asset_triggered__2026-11-19T06:01:02.5+00:00") == (
        "exports/site/runs/asset_triggered__2026-11-19T06_01_02.5_00_00"
    )
    assert run_folder("::") == "exports/site/runs/run"


class RecordingS3:
    """The real (moto) client, recording only the calls publish() itself makes, in order."""

    def __init__(self, client) -> None:
        self.client, self.calls = client, []

    def upload_file(self, filename, bucket, key, **kwargs):
        self.calls.append(("file", key))
        return self.client.upload_file(filename, bucket, key, **kwargs)

    def put_object(self, **kwargs):
        self.calls.append(("object", kwargs["Key"]))
        return self.client.put_object(**kwargs)


def test_publish_writes_files_then_manifest_then_pointer(aws, docs) -> None:
    s3 = RecordingS3(aws[0])
    manifest = publish(s3, BUCKET, "run:1", [docs], release="repo:abc123", now=NOW)

    folder = "exports/site/runs/run_1"
    assert s3.calls == [
        ("file", f"{folder}/dbt-docs.html"),
        ("object", f"{folder}/manifest.json"),
        ("object", POINTER_KEY),  # last: a half-written export is never pointed at
    ]
    assert manifest["folder"] == folder
    assert manifest["exported_at"] == "2026-11-19T06:30:00+00:00"
    assert manifest["release"] == "repo:abc123"
    [entry] = manifest["files"]
    body = s3.client.get_object(Bucket=BUCKET, Key=entry["key"])["Body"].read()
    assert entry["sha256"] == hashlib.sha256(body).hexdigest() and entry["bytes"] == len(body)
    pointer = json.loads(s3.client.get_object(Bucket=BUCKET, Key=POINTER_KEY)["Body"].read())
    assert pointer == manifest


def test_a_file_over_the_budget_publishes_nothing(aws, docs, monkeypatch) -> None:
    s3, _ = aws
    monkeypatch.setattr(site_export, "FILE_BUDGET_BYTES", 10)
    with pytest.raises(ExportTooLarge, match="dbt-docs.html"):
        publish(s3, BUCKET, "run-1", [docs], release="x", now=NOW)
    assert s3.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0


def test_a_new_export_replaces_the_pointer_and_keeps_the_old_folder(aws, docs) -> None:
    s3, _ = aws
    publish(s3, BUCKET, "run-1", [docs], release="x", now=NOW)
    publish(s3, BUCKET, "run-2", [docs], release="x", now=NOW)
    pointer = json.loads(s3.get_object(Bucket=BUCKET, Key=POINTER_KEY)["Body"].read())
    assert pointer["folder"] == "exports/site/runs/run-2"
    s3.head_object(Bucket=BUCKET, Key="exports/site/runs/run-1/manifest.json")  # still there


def test_read_token_refuses_an_empty_secret(aws) -> None:
    _, secrets = aws
    secrets.create_secret(Name="token", SecretString=" ")
    with pytest.raises(DispatchFailed, match="empty"):
        read_token(secrets, "token")
    secrets.put_secret_value(SecretId="token", SecretString="github_pat_x\n")
    assert read_token(secrets, "token") == "github_pat_x"


class FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code, self.text = status_code, text


def test_dispatch_asks_github_to_run_the_site_workflow_on_main() -> None:
    sent = {}

    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return FakeResponse(204)

    dispatch_site_workflow("secret-token", "owner/repo", "exports/site/runs/r", post=post)
    assert (
        sent["url"]
        == "https://api.github.com/repos/owner/repo/actions/workflows/site.yml/dispatches"
    )
    assert sent["json"] == {"ref": "main", "inputs": {"export": "exports/site/runs/r"}}
    assert sent["headers"]["Authorization"] == "Bearer secret-token"


def test_a_refused_dispatch_raises_without_showing_the_token() -> None:
    def post(url, **kwargs):
        return FakeResponse(401, '{"message": "Bad credentials"}')

    with pytest.raises(DispatchFailed) as error:
        dispatch_site_workflow("secret-token", "owner/repo", "f", post=post)
    assert "401" in str(error.value) and "secret-token" not in str(error.value)
