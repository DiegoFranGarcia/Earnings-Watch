"""Build the public site from one published export (run by .github/workflows/site.yml).

The pipeline's publish_site DAG publishes each export to S3 (earningswatch.site_export): the
run's files, its manifest.json, then exports/site/current.json. This reads a manifest (current.json
by default, or one run's manifest.json to roll back), downloads every file it lists, checks each
one's size and sha256 against it, and lays the export out:

    <out>/dbt-docs/index.html   the dbt docs, exactly as the pipeline generated them
    <out>/data/<table>.parquet  each table the pages read (dbt models/exports)
    <out>/site.json             which export is live (run, time, commit), for monitoring

The site's app (site/, ADR 19) is then built from that folder, and --add-app puts the app's
pages beside those files: index.html, one folder per page, and _app/ (its scripts, styles and
fonts). The app may not replace a file of the export, nor the export a page of the app.

Anything unexpected (a file the layout does not know, a hash that does not match, a key outside
the export's folder, a missing table) stops the build, and the site stays as it was.

Standard library only: it runs on a bare GitHub runner, with the AWS CLI for downloads.

    python3 scripts/build_site.py --bucket <lake> --out _site [--export exports/site/runs/<run>]
    (cd site && EW_DATA_DIR=../_site npm run build)
    python3 scripts/build_site.py --add-app site/build --out _site
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
import tempfile
from collections.abc import Callable
from pathlib import Path

POINTER_KEY = "exports/site/current.json"
EXPORT_PATTERN = re.compile(r"exports/site/runs/[A-Za-z0-9._-]+")
NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{7,40}")
FILE_BUDGET_BYTES = 20 * 1024 * 1024  # the same budget the export enforces (site_export.py)
# Where each file of an export goes in the site. A file not listed here stops the build:
# a table joins it in the same change that starts exporting it (site_export.EXPORT_MODELS).
TABLES = (
    "export_screener",
    "export_company_quarters",
    "export_company_history",
    "export_restatements_by_year",
    "export_restatements_largest",
    "export_filing_timeliness",
    "export_pipeline_health",
)
LAYOUT = {
    "dbt-docs.html": "dbt-docs/index.html",
    **{f"{table}.parquet": f"data/{table}.parquet" for table in TABLES},
}
# What every export must hold: everything in the layout, since the app's pages read every table
# when the site is built. An export from before the tables (before 2026-11-19) cannot be deployed.
REQUIRED = set(LAYOUT)
# The export's places in the site, which the app's build may not use.
EXPORT_PLACES = {"data", "dbt-docs", "site.json"}

Download = Callable[[str, str, Path], None]


class BadExport(Exception):
    """The export is incomplete, altered or not what was asked for: nothing is deployed."""


def aws_download(bucket: str, key: str, dest: Path) -> None:
    subprocess.run(  # noqa: S603 - fixed arguments, no shell; the key is validated first
        ["aws", "s3", "cp", "--only-show-errors", f"s3://{bucket}/{key}", str(dest)],  # noqa: S607
        check=True,
    )


def manifest_key(export: str) -> str:
    """current.json for the latest export, or the named run's own manifest (a rollback)."""
    if not export:
        return POINTER_KEY
    if not EXPORT_PATTERN.fullmatch(export):
        raise BadExport(f"not an export folder: {export!r} (expected exports/site/runs/<run>)")
    return f"{export}/manifest.json"


def check_manifest(manifest: object, export: str) -> list[dict]:
    """Every field the build relies on, checked before anything is downloaded."""
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise BadExport("the manifest is not schema 1")
    folder = manifest.get("folder")
    if not isinstance(folder, str) or not EXPORT_PATTERN.fullmatch(folder):
        raise BadExport(f"the manifest's folder is not an export folder: {folder!r}")
    if export and folder != export:
        raise BadExport(f"asked for {export}, but its manifest describes {folder}")
    try:
        datetime.datetime.fromisoformat(manifest["exported_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BadExport("the manifest has no valid exported_at") from exc
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise BadExport("the manifest lists no files")
    names = [entry.get("name") if isinstance(entry, dict) else None for entry in files]
    if len(set(names)) != len(names):
        raise BadExport("the manifest lists a file twice")
    for entry in files:
        name = entry.get("name")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            raise BadExport(f"not a plain file name: {name!r}")
        if name not in LAYOUT:
            raise BadExport(f"{name} is not part of the site's layout (scripts/build_site.py)")
        if entry.get("key") != f"{folder}/{name}":
            raise BadExport(f"{name}'s key is outside the export's folder: {entry.get('key')!r}")
        size = entry.get("bytes")
        if not isinstance(size, int) or not 0 <= size <= FILE_BUDGET_BYTES:
            raise BadExport(f"{name}: {size!r} bytes is not within the budget")
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256"))):
            raise BadExport(f"{name}: no valid sha256")
        rows = entry.get("rows")
        if name.endswith(".parquet") and not (isinstance(rows, int) and rows > 0):
            raise BadExport(f"{name}: a table without a positive row count")
    missing = REQUIRED - set(names)
    if missing:
        raise BadExport(f"the export is missing {', '.join(sorted(missing))}")
    return files


def verify(path: Path, entry: dict) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    size = path.stat().st_size
    if size != entry["bytes"] or digest != entry["sha256"]:
        raise BadExport(
            f"{entry['name']} does not match its manifest: {size:,} bytes, sha256 {digest[:12]} "
            f"(expected {entry['bytes']:,} bytes, sha256 {entry['sha256'][:12]})"
        )


def commit_of(release: object) -> str | None:
    """The commit the export was built from, if the release names one: repository:commit."""
    tail = str(release or "").rsplit(":", 1)[-1]
    return tail if COMMIT_PATTERN.fullmatch(tail) else None


def build(bucket: str, export: str, out: Path, download: Download = aws_download) -> dict:
    """Download, verify and lay out one export into `out`, which must not exist yet."""
    key = manifest_key(export)
    out.mkdir(parents=True)  # fails if it exists: never mix two builds
    with tempfile.TemporaryDirectory(prefix="earningswatch-site-") as tmp:
        scratch = Path(tmp)
        download(bucket, key, scratch / "manifest.json")
        try:
            manifest = json.loads((scratch / "manifest.json").read_text())
        except ValueError as exc:
            raise BadExport(f"{key} is not JSON") from exc
        files = check_manifest(manifest, export)
        for entry in files:
            local = scratch / entry["name"]
            download(bucket, entry["key"], local)
            verify(local, entry)
            target = out / LAYOUT[entry["name"]]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local, target)
    live = {
        "run_id": manifest.get("run_id"),
        "exported_at": manifest["exported_at"],
        "commit": commit_of(manifest.get("release")),
        "folder": manifest["folder"],
        "files": {
            e["name"]: {k: e[k] for k in ("bytes", "rows", "sha256") if k in e} for e in files
        },
    }
    (out / "site.json").write_text(json.dumps(live, indent=2) + "\n")
    return manifest


def add_app(app: Path, out: Path) -> int:
    """Copy the app's build into a laid-out export, beside its files; how many files it copied."""
    if not (out / "site.json").is_file():
        raise BadExport(f"{out} holds no export (site.json): build the export first")
    if not (app / "index.html").is_file():
        raise BadExport(f"{app} is not the app's build (no index.html)")
    files = sorted(p for p in app.rglob("*") if not p.is_dir())
    for path in files:
        rel = path.relative_to(app)
        if path.is_symlink() or not path.is_file():
            raise BadExport(f"the app's build holds something other than a file: {rel}")
        if rel.parts[0] in EXPORT_PLACES or (out / rel).exists():
            raise BadExport(f"the app's build would replace the export's {rel}")
    for path in files:
        target = out / path.relative_to(app)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the site from one export.")
    parser.add_argument("--bucket", help="the lake bucket")
    parser.add_argument("--export", default="", help="exports/site/runs/<run>; empty: latest")
    parser.add_argument("--out", default="_site", type=Path)
    parser.add_argument(
        "--add-app", type=Path, metavar="BUILD", help="instead: put the app's build into --out"
    )
    args = parser.parse_args(argv)
    if args.add_app:
        try:
            copied = add_app(args.add_app, args.out)
        except BadExport as exc:
            print(f"NOT DEPLOYED: {exc}", file=sys.stderr)
            return 1
        print(f"Added the app's {copied} files beside the export in {args.out}.")
        return 0
    if not args.bucket:
        parser.error("--bucket is required to build from an export")
    try:
        manifest = build(args.bucket, args.export, args.out)
    except BadExport as exc:
        print(f"NOT DEPLOYED: {exc}", file=sys.stderr)
        return 1
    lines = [
        f"Built the site from `{manifest['folder']}`, exported {manifest['exported_at']}.",
        "",
        "| File | Bytes | sha256 |",
        "| --- | ---: | --- |",
        *(f"| {e['name']} | {e['bytes']:,} | `{e['sha256'][:12]}` |" for e in manifest["files"]),
    ]
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
