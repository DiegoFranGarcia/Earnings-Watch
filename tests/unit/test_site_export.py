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
    def __init__(self, status_code: int, text: str = "", body: object = None) -> None:
        self.status_code, self.text, self.body = status_code, text, body

    def json(self) -> object:
        if self.body is None:
            raise ValueError("no JSON body")
        return self.body


def test_dispatch_asks_github_to_run_the_site_workflow_on_main() -> None:
    sent = {}
    link = "https://github.com/owner/repo/actions/runs/1"

    def post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return FakeResponse(200, body={"workflow_run_id": 1, "html_url": link})

    run_url = dispatch_site_workflow("secret-token", "owner/repo", "exports/site/runs/r", post=post)
    assert run_url == link
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


@pytest.mark.parametrize("response", [FakeResponse(204), FakeResponse(200, "not json")])
def test_a_created_run_without_a_link_is_still_a_success(response) -> None:
    assert dispatch_site_workflow("t", "owner/repo", "f", post=lambda url, **kw: response) is None


# -- the tables, as Parquet -------------------------------------------------------------------


class FakeCursor:
    """Answers count(*) and select * for the tables it holds, as Snowflake's cursor would."""

    def __init__(self, tables: dict, counts: dict, log: list) -> None:
        self.tables, self.counts, self.log, self.sql = tables, counts, log, ""

    def execute(self, sql: str) -> None:
        self.log.append(sql)
        self.sql = sql

    def _model(self) -> str:
        return self.sql.rsplit(".", 1)[-1]

    def fetchone(self) -> tuple:
        model = self._model()
        return (self.counts.get(model, self.tables[model].num_rows),)

    def fetch_arrow_all(self, force_return_table: bool = False):
        assert force_return_table, "an empty result must come back as a table, not None"
        return self.tables[self._model()]

    def close(self) -> None:
        self.log.append("closed")


class FakeConnection:
    def __init__(self, tables: dict, counts: dict | None = None) -> None:
        self.tables, self.counts, self.log = tables, counts or {}, []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.tables, self.counts, self.log)


def screener_table(rows: int = 3):
    import pyarrow as pa

    return pa.table({"CIK": list(range(rows)), "IS_FLAGGED": [True] * rows})


def test_each_table_becomes_a_zstd_parquet_file_with_lower_case_columns(tmp_path) -> None:
    import pyarrow.parquet as pq

    conn = FakeConnection({"export_screener": screener_table()})
    written = site_export.export_tables(conn, "EARNINGSWATCH_DEV", tmp_path, ["export_screener"])

    path = tmp_path / "export_screener.parquet"
    assert written == {path: 3}
    assert pq.read_table(path).column_names == ["cik", "is_flagged"]
    assert pq.ParquetFile(path).metadata.row_group(0).column(0).compression == "ZSTD"
    assert conn.log == [
        "select count(*) from EARNINGSWATCH_DEV.MARTS.export_screener",
        "select * from EARNINGSWATCH_DEV.MARTS.export_screener",
        "closed",
    ]


def test_a_table_read_short_stops_the_export(tmp_path) -> None:
    conn = FakeConnection({"export_screener": screener_table(3)}, counts={"export_screener": 4})
    with pytest.raises(site_export.ExportIncomplete, match="4 rows in Snowflake, 3 read"):
        site_export.export_tables(conn, "EARNINGSWATCH_DEV", tmp_path, ["export_screener"])
    assert conn.log[-1] == "closed"


def test_an_empty_table_stops_the_export(tmp_path) -> None:
    conn = FakeConnection({"export_screener": screener_table(0)})
    with pytest.raises(site_export.ExportIncomplete, match="0 rows"):
        site_export.export_tables(conn, "EARNINGSWATCH_DEV", tmp_path, ["export_screener"])


@pytest.mark.parametrize(
    ("database", "model"),
    [("DEV; drop table x", "export_screener"), ("EARNINGSWATCH_DEV", "export_screener; --")],
)
def test_only_plain_names_reach_the_sql(tmp_path, database, model) -> None:
    with pytest.raises(ValueError, match="not a"):
        site_export.export_tables(FakeConnection({}), database, tmp_path, [model])


def test_the_manifest_records_each_tables_row_count(aws, docs, tmp_path) -> None:
    s3, _ = aws
    table = tmp_path / "export_screener.parquet"
    table.write_bytes(b"PAR1 stand-in")
    manifest = publish(s3, BUCKET, "run-1", [docs, table], release="x", now=NOW, rows={table: 3})
    by_name = {entry["name"]: entry for entry in manifest["files"]}
    assert by_name["export_screener.parquet"]["rows"] == 3
    assert "rows" not in by_name["dbt-docs.html"]


def test_the_export_tables_match_what_the_site_lays_out() -> None:
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "build_site.py"
    spec = importlib.util.spec_from_file_location("build_site", script)
    build_site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_site)
    assert build_site.TABLES == site_export.EXPORT_MODELS


def test_a_connection_names_its_role_and_warehouse_only_when_asked(monkeypatch) -> None:
    import snowflake.connector

    from earningswatch import snowflake_load

    calls = []
    monkeypatch.setattr(snowflake.connector, "connect", lambda **kwargs: calls.append(kwargs))
    snowflake_load.connect("acct", "SVC_AIRFLOW", "~/k.p8", "EARNINGSWATCH_DEV", "tag")
    snowflake_load.connect(
        "acct", "SVC_AIRFLOW", "~/k.p8", "EARNINGSWATCH_DEV", "tag",
        role="REPORTER", warehouse="WH_REPORTING", schema="MARTS",
    )  # fmt: skip
    loads, site = calls
    assert "role" not in loads and "warehouse" not in loads and loads["schema"] == "RAW"
    assert site["role"] == "REPORTER" and site["warehouse"] == "WH_REPORTING"
    assert site["schema"] == "MARTS"
