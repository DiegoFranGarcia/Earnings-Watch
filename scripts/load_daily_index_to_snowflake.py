"""Load the daily index from silver into Snowflake RAW, one month per transaction, from a laptop.

Each month commits only if RAW holds exactly the rows its silver files contain. Connects as
SVC_AIRFLOW (role LOADER) with its key, like the FSDS loader:

    uv run python scripts/load_daily_index_to_snowflake.py --months 2025-01..2026-11
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "airflow" / "dags"))

from earningswatch.snowflake_load import (  # noqa: E402
    connect,
    daily_index_table_sql,
    load_daily_index_month,
    months_between,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--months", required=True, help="a range, e.g. 2025-01..2026-11")
    parser.add_argument("--database", default="EARNINGSWATCH_DEV")
    parser.add_argument("--account", default=os.environ.get("SF_ACCOUNT", "TOHCGIQ-QM22072"))
    parser.add_argument("--user", default="SVC_AIRFLOW")
    parser.add_argument("--key", default="~/.snowflake/keys/svc_airflow_rsa_key.p8")
    args = parser.parse_args(argv)
    first, _, last = args.months.partition("..")
    months = months_between(first, last or first)

    con = connect(args.account, args.user, args.key, args.database, "earningswatch:load:manual")
    failed: list[str] = []
    total = 0
    started = time.perf_counter()
    try:
        cur = con.cursor()
        cur.execute(daily_index_table_sql())
        for month in months:
            began = time.perf_counter()
            try:
                rows = load_daily_index_month(cur, month)
                total += rows
                print(f"{month}  {rows:>9,} rows  {time.perf_counter() - began:>5.1f}s", flush=True)
            except Exception as exc:  # noqa: BLE001 - reported, and fails the run below
                failed.append(month)
                print(f"{month}  FAILED  {type(exc).__name__}: {exc}"[:300], flush=True)
    finally:
        con.close()
    print(
        f"\n{len(months) - len(failed)} months loaded, {len(failed)} failed, "
        f"{total:,} rows in {time.perf_counter() - started:.0f}s"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
