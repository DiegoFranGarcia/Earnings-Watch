"""Build the public site from one published export (run by .github/workflows/site.yml).

The pipeline's publish_site DAG publishes each export to S3 (earningswatch.site_export): the
run's files, its manifest.json, then exports/site/current.json. This reads a manifest (current.json
by default, or one run's manifest.json to roll back), downloads every file it lists, checks each
one's size and sha256 against it, and assembles the site:

    <out>/index.html            the landing page: what this is, and how fresh its data is
    <out>/dbt-docs/index.html   the dbt docs, exactly as the pipeline generated them
    <out>/data/<table>.parquet  each table the pages read (dbt models/exports)
    <out>/site.json             which export is live (run, time, commit), for monitoring

Anything unexpected (a file the layout does not know, a hash that does not match, a key outside
the export's folder) stops the build, and the site stays as it was.

Standard library only: it runs on a bare GitHub runner, with the AWS CLI for downloads.

    python3 scripts/build_site.py --bucket <lake> --out _site [--export exports/site/runs/<run>]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
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
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
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
# What every export must hold. The tables become required when the pages that read them ship;
# until then an export from before them (the live one, or an older one rolled back to) builds.
REQUIRED = {"dbt-docs.html"}

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


def as_of(exported_at: str) -> str:
    moment = datetime.datetime.fromisoformat(exported_at).astimezone(datetime.UTC)
    return f"{moment:%A %-d %B %Y, %H:%M} UTC"


def landing_page(manifest: dict, repository: str) -> str:
    """The site's front page. Every value from the manifest is escaped."""
    repo_url = f"https://github.com/{repository}"
    commit = commit_of(manifest.get("release"))
    code = (
        f'code <a href="{repo_url}/commit/{commit}"><code>{commit[:12]}</code></a>'
        if commit
        else "code: unknown release"
    )
    when = html.escape(as_of(manifest["exported_at"]))
    stamp = html.escape(manifest["exported_at"])
    run = html.escape(str(manifest.get("run_id", "")))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="description"
      content="SEC EDGAR financial statements, from raw filings to tested models.">
<title>EarningsWatch</title>
<style>
  :root {{ color-scheme: light dark; --fg: #1a1a1a; --muted: #5c5c5c; --bg: #fbfbf9;
          --line: #dcdcd6; --accent: #0b5cad; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg: #ececea; --muted: #a3a3a0; --bg: #161616; --line: #333331; --accent: #7db4ef; }}
  }}
  body {{ margin: 0; background: var(--bg); color: var(--fg);
         font: 17px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 40rem; margin: 0 auto; padding: 4rem 1rem 3rem; }}
  h1 {{ font-size: 2rem; margin: 0 0 .5rem; letter-spacing: -.01em; }}
  p {{ margin: 0 0 1rem; }}
  .lede {{ color: var(--muted); }}
  .fresh {{ border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
           padding: .75rem 0; margin: 2rem 0; font-size: .95rem; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{ margin: 0 0 1.25rem; }}
  a {{ color: var(--accent); }}
  li a {{ font-weight: 600; }}
  li span {{ display: block; color: var(--muted); font-size: .95rem; }}
  footer {{ color: var(--muted); font-size: .85rem; margin-top: 3rem; }}
</style>
</head>
<body>
<main>
  <h1>EarningsWatch</h1>
  <p class="lede">Quarterly financial statements from SEC EDGAR, taken from raw filings to
  tested models by an orchestrated pipeline: S3, Spark on EMR Serverless, Snowflake, dbt
  and Airflow.</p>
  <p class="fresh">Data as of <time datetime="{stamp}">{when}</time> &middot; {code}</p>
  <ul>
    <li><a href="dbt-docs/">dbt docs</a>
      <span>Every model, column and test, with the lineage graph from sources to marts.</span></li>
    <li><a href="{repo_url}">Source code</a>
      <span>The pipeline, its infrastructure as code, tests and design decisions.</span></li>
  </ul>
  <footer>Rebuilt by the pipeline after every dbt build that passes all its tests
  (run <code>{run}</code>).</footer>
</main>
</body>
</html>
"""


def build(
    bucket: str, export: str, out: Path, repository: str, download: Download = aws_download
) -> dict:
    """Download, verify and assemble one export into `out`, which must not exist yet."""
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise BadExport(f"not a repository: {repository!r}")
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
    (out / "index.html").write_text(landing_page(manifest, repository))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the site from one export.")
    parser.add_argument("--bucket", required=True, help="the lake bucket")
    parser.add_argument("--export", default="", help="exports/site/runs/<run>; empty: latest")
    parser.add_argument("--out", default="_site", type=Path)
    parser.add_argument(
        "--repository",
        default=os.environ.get("GITHUB_REPOSITORY", "DiegoFranGarcia/Earnings-Watch"),
    )
    args = parser.parse_args(argv)
    try:
        manifest = build(args.bucket, args.export, args.out, args.repository)
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
