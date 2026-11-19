"""Publish what the public site shows: one folder per run, then one pointer to it.

Each run writes its files to exports/site/runs/<run>/ (the dbt docs, and each table the pages
read as ZSTD Parquet), then manifest.json beside them (every file's size and sha256, each
table's row count, the run, the time, the release), and only then exports/site/current.json,
a copy of that manifest. The site workflow (.github/workflows/site.yml) reads current.json first,
so it always finds a complete export: a run's folder never changes once written, and switching to
a new one is a single PUT. A run that fails halfway leaves current.json, and the site, as they were.

By hand, from the repository root, with your own AWS session and dbt profile:

    uv run python -m earningswatch.site_export --bucket <lake bucket> [--dispatch]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PREFIX = "exports/site"
POINTER_KEY = f"{PREFIX}/current.json"
FILE_BUDGET_BYTES = 20 * 1024 * 1024  # a page loads in the browser: no file may be bigger
DOCS_FILE = "dbt-docs.html"
SITE_WORKFLOW = "site.yml"
# The tables the pages read (dbt models/exports), and how they are read: as REPORTER, which
# can only read MARTS, on its own warehouse, so the site's cost is its own line.
EXPORT_MODELS = (
    "export_screener",
    "export_company_quarters",
    "export_company_history",
    "export_restatements_by_year",
    "export_restatements_largest",
    "export_filing_timeliness",
    "export_pipeline_health",
)
SITE_ROLE = "REPORTER"
SITE_WAREHOUSE = "WH_REPORTING"
GITHUB_API = "https://api.github.com"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json",
                 ".parquet": "application/vnd.apache.parquet"}  # fmt: skip


class ExportTooLarge(Exception):
    """A file is over the size budget: the site would stall loading it."""


class DispatchFailed(Exception):
    """GitHub did not accept the request to run the site workflow."""


class ExportIncomplete(Exception):
    """A table's Parquet file does not hold every row of the table: nothing is published."""


def run_folder(run_id: str) -> str:
    """The run's own folder. Airflow run IDs hold ':' and '+', which are awkward in S3 keys."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", run_id).strip("_") or "run"
    return f"{PREFIX}/runs/{safe}"


def describe(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def generate_dbt_docs(
    dbt_executable: str, project_dir: Path, out_dir: Path, run_label: str
) -> Path:
    """Run `dbt docs generate --static`: one self-contained HTML file, with the catalog.

    dbt writes target/ and logs/ to a scratch folder, so the project folder can stay read-only.
    The run label tags every Snowflake query, for cost attribution.
    """
    scratch = out_dir / "dbt-scratch"
    # dbt_executable comes from our own settings, never from user input; no shell.
    subprocess.run(  # noqa: S603
        [
            dbt_executable, "docs", "generate", "--static",
            "--project-dir", str(project_dir), "--profiles-dir", str(project_dir),
            "--target-path", str(scratch / "target"), "--log-path", str(scratch / "logs"),
        ],
        check=True,
        env={**os.environ, "DBT_RUN_LABEL": run_label},
    )  # fmt: skip
    docs = out_dir / DOCS_FILE
    shutil.move(str(scratch / "target" / "static_index.html"), docs)
    return docs


def export_tables(conn, database: str, out_dir: Path, models=EXPORT_MODELS) -> dict[Path, int]:
    """Write each export model to a ZSTD Parquet file, with lower-case columns; return the rows.

    Each file is read back and its row count compared with count(*) of the table, so a short
    read or write stops the export instead of publishing part of a table.
    """
    import pyarrow.parquet as pq

    if not re.fullmatch(r"[A-Za-z0-9_]+", database):
        raise ValueError(f"not a database name: {database!r}")
    written = {}
    for model in models:
        if not re.fullmatch(r"[a-z0-9_]+", model):
            raise ValueError(f"not a model name: {model!r}")
        relation = f"{database}.MARTS.{model}"  # both names checked above: no injection
        cursor = conn.cursor()
        try:
            cursor.execute(f"select count(*) from {relation}")  # noqa: S608
            expected = cursor.fetchone()[0]
            cursor.execute(f"select * from {relation}")  # noqa: S608
            table = cursor.fetch_arrow_all(force_return_table=True)
        finally:
            cursor.close()
        table = table.rename_columns([name.lower() for name in table.column_names])
        path = out_dir / f"{model}.parquet"
        pq.write_table(table, path, compression="zstd")
        rows = pq.ParquetFile(path).metadata.num_rows
        if rows == 0 or not expected == table.num_rows == rows:
            raise ExportIncomplete(
                f"{model}: {expected:,} rows in Snowflake, {table.num_rows:,} read, "
                f"{rows:,} written"
            )
        written[path] = rows
    return written


def publish(
    s3, bucket: str, run_id: str, files: list[Path], release: str, now=None, rows=None
) -> dict:
    """Upload the files to the run's folder, then its manifest, then the pointer: in that order.

    rows maps a table's file to its row count, recorded in the manifest beside the file.
    """
    now = now or datetime.datetime.now(datetime.UTC)
    entries = [describe(path) for path in files]
    for path, entry in zip(files, entries, strict=True):
        if rows and path in rows:
            entry["rows"] = rows[path]
    too_big = [e for e in entries if e["bytes"] > FILE_BUDGET_BYTES]
    if too_big:
        raise ExportTooLarge(
            ", ".join(f"{e['name']} is {e['bytes']:,} bytes" for e in too_big)
            + f"; the budget is {FILE_BUDGET_BYTES:,} bytes per file"
        )
    folder = run_folder(run_id)
    for path, entry in zip(files, entries, strict=True):
        entry["key"] = f"{folder}/{entry['name']}"
        content_type = CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        s3.upload_file(
            str(path), bucket, entry["key"],
            ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": entry["sha256"]}},
        )  # fmt: skip
    manifest = {
        "schema": 1,
        "run_id": run_id,
        "exported_at": now.isoformat(timespec="seconds"),
        "release": release,
        "folder": folder,
        "files": entries,
    }
    body = json.dumps(manifest, indent=2).encode()
    s3.put_object(
        Bucket=bucket, Key=f"{folder}/manifest.json", Body=body, ContentType="application/json"
    )
    s3.put_object(Bucket=bucket, Key=POINTER_KEY, Body=body, ContentType="application/json")
    return manifest


def read_token(secrets, secret_id: str) -> str:
    """The token that starts the site workflow, read when it is needed and never written down."""
    token = secrets.get_secret_value(SecretId=secret_id).get("SecretString", "").strip()
    if not token:
        raise DispatchFailed(f"the secret {secret_id} is empty: set it with the AWS CLI (runbook)")
    return token


def dispatch_site_workflow(token: str, repository: str, folder: str, ref: str = "main", post=None):
    """Start the site workflow on main, naming the export it should deploy.

    Returns the new run's link when GitHub gives one: it now answers 200 with the run's ID
    and links; it used to answer 204 with no body. Both mean the run was created.
    """
    if post is None:
        import requests

        post = requests.post
    response = post(
        f"{GITHUB_API}/repos/{repository}/actions/workflows/{SITE_WORKFLOW}/dispatches",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"ref": ref, "inputs": {"export": folder}},
        timeout=30,
    )
    if response.status_code not in (200, 204):  # the token itself never appears in the message
        raise DispatchFailed(f"GitHub answered {response.status_code}: {response.text[:300]}")
    if response.status_code == 204:
        return None
    try:
        return response.json().get("html_url")
    except (ValueError, AttributeError):  # the run exists; only its link is missing
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish the site's export by hand (see docstring)."
    )
    parser.add_argument("--bucket", default=os.environ.get("LAKE_BUCKET"), help="the lake bucket")
    parser.add_argument("--run-id", default=None, help="default: manual-<UTC time>")
    parser.add_argument("--dbt", default="dbt", help="the dbt executable")
    parser.add_argument("--project-dir", default="dbt", type=Path)
    parser.add_argument("--dispatch", action="store_true", help="then start the site workflow")
    parser.add_argument("--secret-id", default=os.environ.get("SITE_DISPATCH_SECRET_ID",
                        "earningswatch/dev/github-dispatch-token"))  # fmt: skip
    parser.add_argument("--repository", default=os.environ.get("SITE_GITHUB_REPOSITORY",
                        "DiegoFranGarcia/Earnings-Watch"))  # fmt: skip
    # Snowflake, as SVC_AIRFLOW with its own key (read as REPORTER, like the DAG).
    parser.add_argument("--sf-account", default=os.environ.get("SF_ACCOUNT", "TOHCGIQ-QM22072"))
    parser.add_argument("--sf-user", default=os.environ.get("SF_USER", "SVC_AIRFLOW"))
    parser.add_argument("--sf-key", default=os.environ.get("SF_PRIVATE_KEY_PATH",
                        "~/.snowflake/keys/svc_airflow_rsa_key.p8"))  # fmt: skip
    parser.add_argument("--sf-database", default=os.environ.get("SF_DATABASE", "EARNINGSWATCH_DEV"))
    args = parser.parse_args(argv)
    if not args.bucket:
        parser.error("--bucket (or LAKE_BUCKET) is required")
    import tempfile

    import boto3

    now = datetime.datetime.now(datetime.UTC)
    run_id = args.run_id or f"manual-{now:%Y%m%dT%H%M%SZ}"
    commit = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],  # noqa: S607 - by hand only: git from PATH
        capture_output=True,
        text=True,
    )
    release = f"local:{commit.stdout.strip() or 'unknown'}"
    from earningswatch import snowflake_load

    with tempfile.TemporaryDirectory(prefix="earningswatch-site-") as tmp:
        conn = snowflake_load.connect(
            args.sf_account, args.sf_user, args.sf_key, args.sf_database,
            f"earningswatch:site:{run_id}",
            role=SITE_ROLE, warehouse=SITE_WAREHOUSE, schema="MARTS",
        )  # fmt: skip
        try:
            tables = export_tables(conn, args.sf_database, Path(tmp))
        finally:
            conn.close()
        docs = generate_dbt_docs(args.dbt, args.project_dir, Path(tmp), run_id)
        manifest = publish(
            boto3.client("s3"), args.bucket, run_id, [docs, *tables], release, now, rows=tables
        )
    # dbt has already written its own output to stdout: end with a short summary, not JSON.
    # The full manifest is exports/site/current.json.
    print(f"published {manifest['folder']} ({POINTER_KEY} points at it):")
    for entry in manifest["files"]:
        rows = f", {entry['rows']:,} rows" if "rows" in entry else ""
        print(f"  {entry['name']}: {entry['bytes']:,} bytes{rows}, sha256 {entry['sha256'][:12]}")
    if args.dispatch:
        token = read_token(boto3.client("secretsmanager", region_name="us-east-1"), args.secret_id)
        run_url = dispatch_site_workflow(token, args.repository, manifest["folder"])
        print(f"started {SITE_WORKFLOW} for {manifest['folder']}: {run_url or args.repository}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
