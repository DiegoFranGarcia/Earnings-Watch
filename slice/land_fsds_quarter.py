"""Slice step 1: land one quarter of the Financial Statement Data Sets in bronze.

Downloads the quarter's ZIP from the SEC (once), then extracts its four
tab-separated files next to it (once each). Safe to run any number of times.

Usage:
    PYTHONPATH=airflow/dags uv run python slice/land_fsds_quarter.py 2026q3
"""

from __future__ import annotations

import argparse
import logging

import boto3

from earningswatch import fsds
from earningswatch.bronze import extract_zip, land_file
from earningswatch.config import load_settings
from earningswatch.sec_client import SecClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Land one FSDS quarter in bronze.")
    parser.add_argument("quarter", help="for example 2026q3")
    quarter = fsds.validate_quarter(parser.parse_args().quarter)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings()
    s3 = boto3.client("s3")
    url = fsds.zip_url(quarter, settings.fsds_base_url)
    key = fsds.zip_key(quarter)

    with SecClient(settings.sec_user_agent, settings.sec_rate_per_second) as sec:
        if not sec.exists(url):
            raise SystemExit(f"The SEC has not published {quarter} (yet): {url}")
        landed = land_file(sec, s3, url, settings.lake_bucket, key)

    zip_status = "downloaded" if landed.downloaded else "already in bronze"
    print(f"\n{quarter}.zip  {zip_status}  {landed.manifest.size_bytes:,} bytes")

    print(f"\n{'member':<9} {'status':<15} {'bytes':>15} {'data rows':>12}")
    for result in extract_zip(s3, settings.lake_bucket, key, fsds.FSDS_MEMBERS):
        status = "extracted" if result.extracted else "already there"
        rows = (result.manifest.line_count or 1) - 1  # minus the header line
        print(f"{result.member:<9} {status:<15} {result.manifest.size_bytes:>15,} {rows:>12,}")


if __name__ == "__main__":
    main()
