"""Generate Airflow's own secrets once, and store them in Secrets Manager as JSON:

- POSTGRES_PASSWORD: the metadata database's password;
- FERNET_KEY: encrypts connections and variables stored in that database;
- AIRFLOW__API_AUTH__JWT_SECRET: signs the API's tokens;
- _AIRFLOW_WWW_USER_PASSWORD: the admin user's password;
- SEC_USER_AGENT: sent to the SEC (not secret, but kept out of the repository with the rest).

These must survive a rebuild of the host (a restored database is encrypted with the old Fernet
key), so the script refuses to overwrite an existing value. Values go from memory to Secrets
Manager through boto3: never through a file, a command line or the screen.

    uv run python scripts/create_airflow_internals_secret.py
"""

from __future__ import annotations

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


def main() -> int:
    client = boto3.client("secretsmanager", region_name="us-east-1")
    try:
        client.get_secret_value(SecretId=SECRET_ID)
    except client.exceptions.ResourceNotFoundException as exc:
        if "can't find the specified secret value" not in str(exc).lower():
            raise  # the secret itself is missing: apply Terraform first
    else:
        print(
            f"{SECRET_ID} already has a value; not overwriting it (a rebuild needs the same keys)"
        )
        return 0

    values = {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "FERNET_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "AIRFLOW__API_AUTH__JWT_SECRET": secrets.token_urlsafe(48),
        "_AIRFLOW_WWW_USER_PASSWORD": secrets.token_urlsafe(18),
        "SEC_USER_AGENT": sec_user_agent(),
    }
    client.put_secret_value(SecretId=SECRET_ID, SecretString=json.dumps(values))
    print(f"stored in {SECRET_ID}:", ", ".join(values))
    return 0


if __name__ == "__main__":
    sys.exit(main())
