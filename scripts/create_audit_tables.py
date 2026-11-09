"""Create the AUDIT tables that Airflow writes, as SVC_AIRFLOW (role LOADER), so they exist (and
LOADER owns them) before the first run writes to them. Idempotent: safe to run any time.

    uv run python scripts/create_audit_tables.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "airflow" / "dags"))

from earningswatch.costs import EMR_TABLE_SQL  # noqa: E402
from earningswatch.snowflake_load import connect  # noqa: E402
from earningswatch.volume import DQ_TABLE_SQL  # noqa: E402


def main() -> int:
    con = connect(
        os.environ.get("SF_ACCOUNT", "TOHCGIQ-QM22072"),
        "SVC_AIRFLOW",
        "~/.snowflake/keys/svc_airflow_rsa_key.p8",
        os.environ.get("SF_DATABASE", "EARNINGSWATCH_DEV"),
        "earningswatch:setup:manual",
    )
    try:
        cursor = con.cursor()
        for sql in (DQ_TABLE_SQL, EMR_TABLE_SQL):
            cursor.execute(sql)
            print(sql.split("(")[0].replace("CREATE TABLE IF NOT EXISTS ", "ready: "))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
