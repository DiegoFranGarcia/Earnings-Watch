"""Load FSDS quarters from silver into Snowflake RAW, from a laptop.

Uses the same module Airflow will use. Connects as SVC_AIRFLOW (role LOADER) with its key:

    uv run python scripts/load_fsds_to_snowflake.py --quarters 2026q3
    uv run python scripts/load_fsds_to_snowflake.py --quarters 2009q2..2026q3
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "airflow" / "dags"), str(ROOT / "spark")]

from earningswatch.snowflake_load import (  # noqa: E402
    TABLES,
    create_table_sql,
    expected_rows,
    load_quarter,
)
from lib.quarters import expand  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quarters", required=True, help="a list or range, e.g. 2009q2..2026q3")
    parser.add_argument("--database", default="EARNINGSWATCH_DEV")
    parser.add_argument("--account", default=os.environ.get("SF_ACCOUNT", "TOHCGIQ-QM22072"))
    parser.add_argument("--user", default="SVC_AIRFLOW")
    parser.add_argument("--key", default="~/.snowflake/keys/svc_airflow_rsa_key.p8")
    parser.add_argument(
        "--bucket", default=os.environ.get("LAKE_BUCKET", "earnings-watch-dev-097040011808")
    )
    args = parser.parse_args(argv)
    quarters = expand(args.quarters)

    import boto3
    import snowflake.connector

    s3 = boto3.client("s3")
    con = snowflake.connector.connect(
        account=args.account,
        user=args.user,
        authenticator="SNOWFLAKE_JWT",
        private_key_file=os.path.expanduser(args.key),
        database=args.database,
        schema="RAW",
        session_parameters={"QUERY_TAG": "earningswatch:load:manual"},
    )
    failed: list[str] = []
    started = time.perf_counter()
    try:
        cur = con.cursor()
        for table, columns in TABLES.values():
            cur.execute(create_table_sql(table, columns))
        for quarter in quarters:
            began = time.perf_counter()
            try:
                result = load_quarter(cur, quarter, expected_rows(s3, args.bucket, quarter))
                print(
                    f"{quarter:<8} sub {result.rows['sub']:>8,}  num {result.rows['num']:>11,}"
                    f"  {time.perf_counter() - began:>5.1f}s",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - reported, and fails the run below
                failed.append(quarter)
                print(f"{quarter:<8} FAILED  {type(exc).__name__}: {exc}"[:300], flush=True)
    finally:
        con.close()
    print(
        f"\n{len(quarters) - len(failed)} loaded, {len(failed)} failed, "
        f"in {time.perf_counter() - started:.0f}s"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
