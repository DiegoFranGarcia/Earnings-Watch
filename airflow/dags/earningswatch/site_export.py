"""Publish what the public site shows: one folder per run, then one pointer to it.

Each run writes its files to exports/site/runs/<run>/, then manifest.json beside them (every
file's size and sha256, the run, the time, the release), and only then exports/site/current.json,
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
GITHUB_API = "https://api.github.com"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json",
                 ".parquet": "application/vnd.apache.parquet"}  # fmt: skip


class ExportTooLarge(Exception):
    """A file is over the size budget: the site would stall loading it."""


class DispatchFailed(Exception):
    """GitHub did not accept the request to run the site workflow."""


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


def publish(s3, bucket: str, run_id: str, files: list[Path], release: str, now=None) -> dict:
    """Upload the files to the run's folder, then its manifest, then the pointer: in that order."""
    now = now or datetime.datetime.now(datetime.UTC)
    entries = [describe(path) for path in files]
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
    """Start the site workflow on main, naming the export it should deploy."""
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
    if response.status_code != 204:  # the token itself never appears in the message
        raise DispatchFailed(f"GitHub answered {response.status_code}: {response.text[:300]}")


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
    with tempfile.TemporaryDirectory(prefix="earningswatch-site-") as tmp:
        docs = generate_dbt_docs(args.dbt, args.project_dir, Path(tmp), run_id)
        manifest = publish(boto3.client("s3"), args.bucket, run_id, [docs], release, now)
    # dbt has already written its own output to stdout: end with a short summary, not JSON.
    # The full manifest is exports/site/current.json.
    print(f"published {manifest['folder']} ({POINTER_KEY} points at it):")
    for entry in manifest["files"]:
        print(f"  {entry['name']}: {entry['bytes']:,} bytes, sha256 {entry['sha256'][:12]}")
    if args.dispatch:
        token = read_token(boto3.client("secretsmanager", region_name="us-east-1"), args.secret_id)
        dispatch_site_workflow(token, args.repository, manifest["folder"])
        print(f"started {SITE_WORKFLOW} on {args.repository} for {manifest['folder']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
