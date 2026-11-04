"""Reconcile the bronze zone: do the manifests agree with what is in S3, and is anything missing?

Run from the repository root:

    AWS_PROFILE=earnings-watch uv run python scripts/reconcile_bronze.py

Exits with status 1 on an integrity problem, so it can gate other steps later.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "airflow" / "dags"))

import boto3  # noqa: E402 - after the path setup above

from earningswatch import fsds  # noqa: E402
from earningswatch.reconcile import (  # noqa: E402
    business_days_between,
    load_bronze,
    quarters_between,
    reconcile,
    summarise,
)


def main(argv: list[str] | None = None) -> int:
    today = dt.datetime.now(dt.UTC).date()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", default=os.environ.get("LAKE_BUCKET"))
    parser.add_argument("--first-quarter", default="2009q2")
    parser.add_argument("--last-quarter", default=fsds.previous_quarter(today))
    parser.add_argument("--daily-from", type=dt.date.fromisoformat, default=dt.date(2025, 1, 1))
    parser.add_argument(
        "--daily-through", type=dt.date.fromisoformat, default=today - dt.timedelta(days=2)
    )
    args = parser.parse_args(argv)
    if not args.bucket:
        parser.error("give --bucket, or set LAKE_BUCKET")

    objects, manifest_sizes = load_bronze(boto3.client("s3"), args.bucket)
    report = reconcile(
        objects,
        manifest_sizes,
        quarters_between(args.first_quarter, args.last_quarter),
        business_days_between(args.daily_from, args.daily_through),
    )
    print("\n".join(summarise(report, args.bucket)))
    return 0 if report.integrity_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
