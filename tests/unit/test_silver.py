"""Unit tests for writing silver Parquet."""

from __future__ import annotations

import datetime as dt

import boto3
import pyarrow.parquet as pq
import pytest
from moto import mock_aws

from earningswatch.daily_index import Filing
from earningswatch.silver import replace_partition, write_filings

FILING = Filing(
    cik=2488,
    company_name="ADVANCED MICRO DEVICES INC",
    form_type="8-K",
    date_filed=dt.date(2026, 10, 23),
    filename="edgar/data/2488/0000002488-26-000150.txt",
    accession_number="0000002488-26-000150",
)


def test_write_filings_uses_real_types(tmp_path) -> None:
    path = tmp_path / "part-0.parquet"

    assert write_filings([FILING, FILING], path) == 2

    table = pq.read_table(path)
    assert table.schema.field("cik").type == "int64"
    assert table.schema.field("date_filed").type == "date32[day]"
    assert table.column("accession_number").to_pylist() == ["0000002488-26-000150"] * 2


def test_write_filings_handles_a_day_with_no_filings(tmp_path) -> None:
    path = tmp_path / "part-0.parquet"
    assert write_filings([], path) == 0
    assert pq.read_table(path).num_rows == 0


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


def test_replace_partition_leaves_exactly_one_file(s3, tmp_path) -> None:
    key = "silver/daily_index/date=2026-10-23/part-0.parquet"
    s3.put_object(Bucket="lake", Key="silver/daily_index/date=2026-10-23/stale.parquet", Body=b"x")
    s3.put_object(Bucket="lake", Key="silver/daily_index/date=2026-10-24/part-0.parquet", Body=b"y")
    local = tmp_path / "part-0.parquet"
    local.write_bytes(b"new")

    replace_partition(s3, "lake", local, key)

    keys = sorted(obj["Key"] for obj in s3.list_objects_v2(Bucket="lake")["Contents"])
    assert keys == [
        "silver/daily_index/date=2026-10-23/part-0.parquet",
        "silver/daily_index/date=2026-10-24/part-0.parquet",  # other days are untouched
    ]
