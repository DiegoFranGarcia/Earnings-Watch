"""The airflow-internals secret: a new key is added beside the stored ones, never replacing one.

A stored value must survive (a restored metadata database is encrypted with the old Fernet key).
Secrets Manager is faked with moto; no AWS calls.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "create_airflow_internals_secret", ROOT / "scripts" / "create_airflow_internals_secret.py"
)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

STORED = {
    "POSTGRES_PASSWORD": "pg",
    "FERNET_KEY": "fernet",
    "AIRFLOW__API_AUTH__JWT_SECRET": "jwt",
    "_AIRFLOW_WWW_USER_PASSWORD": "admin",
    "SEC_USER_AGENT": "EarningsWatch someone@example.com",
}


@pytest.fixture
def secretsmanager(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        client = boto3.client("secretsmanager", region_name="us-east-1")
        client.create_secret(Name=script.SECRET_ID)
        yield client


def stored(client) -> dict:
    return json.loads(client.get_secret_value(SecretId=script.SECRET_ID)["SecretString"])


def test_an_existing_secret_gains_only_the_missing_key(secretsmanager, capsys) -> None:
    secretsmanager.put_secret_value(SecretId=script.SECRET_ID, SecretString=json.dumps(STORED))
    assert script.main([]) == 0
    after = stored(secretsmanager)
    assert {k: after[k] for k in STORED} == STORED
    assert len(after["TASK_HISTORY_PASSWORD"]) >= 24
    output = capsys.readouterr().out
    assert "added TASK_HISTORY_PASSWORD" in output
    assert after["TASK_HISTORY_PASSWORD"] not in output and "fernet" not in output


def test_a_complete_secret_is_left_alone(secretsmanager, capsys) -> None:
    complete = {**STORED, "TASK_HISTORY_PASSWORD": "kept"}
    secretsmanager.put_secret_value(SecretId=script.SECRET_ID, SecretString=json.dumps(complete))
    assert script.main([]) == 0
    assert stored(secretsmanager) == complete
    assert "nothing changed" in capsys.readouterr().out


def test_a_new_secret_gets_every_key(secretsmanager, monkeypatch: pytest.MonkeyPatch) -> None:
    generators = {**script.GENERATORS, "SEC_USER_AGENT": lambda: "EarningsWatch x@example.com"}
    monkeypatch.setattr(script, "GENERATORS", generators)
    assert script.main([]) == 0
    assert set(stored(secretsmanager)) == set(generators)


def test_rotating_replaces_only_that_key(secretsmanager, capsys) -> None:
    before = {**STORED, "TASK_HISTORY_PASSWORD": "old"}
    secretsmanager.put_secret_value(SecretId=script.SECRET_ID, SecretString=json.dumps(before))
    assert script.main(["--rotate", "TASK_HISTORY_PASSWORD"]) == 0
    after = stored(secretsmanager)
    assert after["TASK_HISTORY_PASSWORD"] not in ("old", "")
    assert {k: after[k] for k in STORED} == STORED
    assert "replaced TASK_HISTORY_PASSWORD" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        script.main(["--rotate", "FERNET_KEY"])
