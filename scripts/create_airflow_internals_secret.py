"""Generate Airflow's own secrets once, and store them in Secrets Manager as JSON:

- POSTGRES_PASSWORD: the metadata database's password;
- FERNET_KEY: encrypts connections and variables stored in that database;
- AIRFLOW__API_AUTH__JWT_SECRET: signs the API's tokens;
- _AIRFLOW_WWW_USER_PASSWORD: the admin user's password;
- TASK_HISTORY_PASSWORD: the password of task-history, the read-only (Viewer) user
  record_task_history signs in to Airflow's API as;
- SEC_USER_AGENT: sent to the SEC (not secret, but kept out of the repository with the rest).

These must survive a rebuild of the host (a restored database is encrypted with the old Fernet
key), so the script never changes a value already stored. Run against a secret that already
exists, it adds only the keys it lacks (as when a new one, like TASK_HISTORY_PASSWORD, joins the
list). Values go from memory to Secrets Manager through boto3: never through a file, a command
line or the screen.

    uv run python scripts/create_airflow_internals_secret.py

To rotate task-history's password (each February, with the GitHub token), replace that one key;
the host sets it on task-history at its next start (airflow-init in deploy/compose.yaml):

    uv run python scripts/create_airflow_internals_secret.py --rotate TASK_HISTORY_PASSWORD
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
from pathlib import Path

import boto3

SECRET_ID = "earningswatch/dev/airflow-internals"  # noqa: S105 - the secret's name, not a value


def sec_user_agent() -> str:
    for line in Path("airflow/.env").read_text().splitlines():
        if line.startswith("SEC_USER_AGENT="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("SEC_USER_AGENT not found in airflow/.env")


# How to make each value. Only the keys a secret lacks are made, so a run that adds one key
# reads nothing it does not need (SEC_USER_AGENT comes from airflow/.env).
GENERATORS = {
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
    "FERNET_KEY": lambda: base64.urlsafe_b64encode(os.urandom(32)).decode(),
    "AIRFLOW__API_AUTH__JWT_SECRET": lambda: secrets.token_urlsafe(48),
    "_AIRFLOW_WWW_USER_PASSWORD": lambda: secrets.token_urlsafe(18),
    "TASK_HISTORY_PASSWORD": lambda: secrets.token_urlsafe(18),
    "SEC_USER_AGENT": sec_user_agent,
}


def merged(stored: dict[str, str], generators=None) -> tuple[dict[str, str], list[str]]:
    """The stored values, unchanged, plus a new value for each key not yet stored."""
    generators = generators or GENERATORS
    added = [key for key in generators if key not in stored]
    return {**stored, **{key: generators[key]() for key in added}}, added


# Keys safe to replace: whatever uses them is set again from the secret at every start. The
# others are not (the Fernet key encrypts the database; the admin user keeps its first password).
ROTATABLE = ("TASK_HISTORY_PASSWORD",)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rotate", choices=ROTATABLE, help="replace this key's value")
    args = parser.parse_args(argv)
    client = boto3.client("secretsmanager", region_name="us-east-1")
    try:
        stored = json.loads(client.get_secret_value(SecretId=SECRET_ID)["SecretString"])
    except client.exceptions.ResourceNotFoundException as exc:
        if "can't find the specified secret value" not in str(exc).lower():
            raise  # the secret itself is missing: apply Terraform first
        stored = {}

    if args.rotate:
        if args.rotate not in stored:
            raise SystemExit(f"{args.rotate} is not stored yet: run without --rotate first")
        stored = {key: value for key, value in stored.items() if key != args.rotate}
    values, added = merged(stored)
    if not added:
        print(f"{SECRET_ID} already has every key; nothing changed")
        return 0
    client.put_secret_value(SecretId=SECRET_ID, SecretString=json.dumps(values))
    kept = [key for key in values if key not in added]
    action = "replaced" if args.rotate else "added"
    kept_note = f"; kept {', '.join(kept)}" if kept else ""
    print(f"{SECRET_ID}: {action} {', '.join(added)}{kept_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
