"""Check the live site as a visitor's browser gets it, after every deploy (site.yml, `verify`).

The browser tests run against a server that imitates GitHub Pages (site/tests/serve.mjs), but only
the real site shows what Pages actually serves: on 2026-11-21 it turned out to compress every
response and to answer a byte range from the gzip copy when gzip is offered, which no test had
seen (ADR 20). This asks the live site for what the SQL page downloads, with the headers a browser
sends, and compares it with what was deployed:

1. site.json, until it names the export just deployed (Pages may serve the previous one for a
   few minutes), and lists exactly the deployed files.
2. Every table, whole, at the address the SQL page uses (data/<table>.parquet?v=<run ID>): after
   undoing Pages' compression, each must have site.json's size and sha256.
3. DuckDB's engine, its worker and its Parquet extension: each must be the deployed file.
4. The SQL page's "downloads about N MB": what Pages actually sent for all of the above must be
   within 10% of it (plus rounding), so the estimate made at build stays true.

Any difference fails the job (the site is already live; the failure is the alert). The step
summary records each file's status, encoding and the bytes sent. Standard library only, no
credentials: it reads the public site and the Pages artifact the deploy published.

    python3 scripts/verify_live_site.py --site-dir _deployed --url https://<user>.github.io/<repo>/
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# What a browser sends; Pages chooses the compression from it.
BROWSER_HEADERS = {
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "User-Agent": "EarningsWatch live-site check (GitHub Actions)",
}
LABEL = re.compile(r"downloads about (\d+) MB")
TOLERANCE = 0.10  # of the bytes actually sent, beyond the label's rounding to whole MB
# The SQL page's DuckDB files, as the build names them (Vite adds a content hash).
ENGINE_GLOBS = (
    "_app/immutable/assets/duckdb-eh.*.wasm",
    "_app/immutable/assets/duckdb-browser-eh.worker.*.js",
)
EXTENSION_GLOB = "duckdb/*/*/*.duckdb_extension.wasm"


@dataclass
class Response:
    status: int
    encoding: str | None
    body: bytes  # as sent, before undoing any compression


Fetch = Callable[[str], Response]


class Problem(Exception):
    """The live site does not serve what was deployed."""


def fetch(url: str) -> Response:
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)  # noqa: S310 - https only, below
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            return Response(
                response.status, response.headers.get("Content-Encoding"), response.read()
            )
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.headers.get("Content-Encoding"), exc.read())


def decoded(response: Response, url: str) -> bytes:
    """The file itself: Pages' compression undone, as the browser undoes it."""
    encoding = (response.encoding or "identity").lower()
    if encoding == "identity":
        return response.body
    if encoding == "gzip":
        return gzip.decompress(response.body)
    if encoding == "deflate":
        return zlib.decompress(response.body)
    # A browser could read it, but this check cannot: a change at Pages worth knowing about.
    raise Problem(
        f"{url}: Pages now sends {encoding}, which this check cannot decode: extend decoded()"
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def wait_for_export(base: str, expected: dict, get: Fetch, timeout: float, interval: float) -> dict:
    """The live site.json, once it names the deployed export."""
    url = f"{base}site.json"
    deadline = time.monotonic() + timeout
    seen = None
    while True:
        response = get(url)
        if response.status == 200:
            live = json.loads(decoded(response, url))
            seen = live.get("run_id")
            if seen == expected.get("run_id"):
                if live.get("files") != expected.get("files"):
                    raise Problem("site.json names the deployed export but lists other files")
                return live
        if time.monotonic() >= deadline:
            raise Problem(
                f"after {timeout:.0f} s, {url} still says {seen!r} "
                f"(HTTP {response.status}), not the deployed {expected.get('run_id')!r}"
            )
        time.sleep(interval)


def one(site_dir: Path, pattern: str) -> Path:
    found = sorted(site_dir.glob(pattern))
    if len(found) != 1:
        raise Problem(f"the deployed site holds {len(found)} files matching {pattern}, not 1")
    return found[0]


def check(
    site_dir: Path,
    base: str,
    get: Fetch = fetch,
    timeout: float = 720,
    interval: float = 15,
) -> tuple[list[str], list[str]]:
    """(problems, summary lines). No problems: the live site serves exactly what was deployed."""
    base = base if base.endswith("/") else f"{base}/"
    problems: list[str] = []
    rows: list[str] = []
    sent = 0
    expected = json.loads((site_dir / "site.json").read_text())
    try:
        wait_for_export(base, expected, get, timeout, interval)
    except Problem as exc:
        return [str(exc)], rows
    run_id = urllib.parse.quote(str(expected["run_id"]), safe="!~*'()")  # as encodeURIComponent

    # (what the page downloads, the URL it uses, the size and sha256 it must have)
    wanted: list[tuple[str, str, int, str]] = []
    for name, entry in sorted(expected["files"].items()):
        if name.endswith(".parquet"):
            wanted.append((name, f"{base}data/{name}?v={run_id}", entry["bytes"], entry["sha256"]))
    try:
        for path in [*(one(site_dir, g) for g in ENGINE_GLOBS), one(site_dir, EXTENSION_GLOB)]:
            data = path.read_bytes()
            rel = path.relative_to(site_dir).as_posix()
            wanted.append((rel, f"{base}{rel}", len(data), sha256(data)))
    except Problem as exc:
        problems.append(str(exc))

    for name, url, size, digest in wanted:
        response = get(url)
        if response.status != 200:
            problems.append(f"{url}: HTTP {response.status}")
            rows.append(f"| {name} | {response.status} | | | |")
            continue
        sent += len(response.body)
        try:
            data = decoded(response, url)
        except (Problem, OSError, zlib.error) as exc:
            problems.append(f"{url}: {exc}")
            continue
        same = len(data) == size and sha256(data) == digest
        if not same:
            problems.append(
                f"{url}: {len(data):,} bytes with sha256 {sha256(data)[:12]}, "
                f"deployed {size:,} bytes with sha256 {digest[:12]}"
            )
        rows.append(
            f"| {name} | 200 | {response.encoding or 'none'} | {len(response.body):,} | "
            f"{'yes' if same else '**no**'} |"
        )

    label = LABEL.search((site_dir / "sql" / "index.html").read_text())
    if not label:
        problems.append("sql/index.html has no 'downloads about N MB'")
    elif not problems:
        claimed, actual = int(label.group(1)), sent / 1e6
        rows.append(f"\nThe SQL page says about {claimed} MB; Pages sent {actual:.1f} MB.")
        if abs(claimed - actual) > 0.5 + TOLERANCE * actual:
            problems.append(f"the SQL page says about {claimed} MB, but Pages sent {actual:.1f} MB")
    return problems, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the live site against what was deployed.")
    parser.add_argument("--site-dir", type=Path, required=True, help="the deployed Pages artifact")
    parser.add_argument("--url", required=True, help="the site's address (https://...)")
    parser.add_argument("--timeout", type=float, default=720, help="seconds to wait for site.json")
    args = parser.parse_args(argv)
    if not args.url.startswith("https://"):
        parser.error("--url must be https://")
    problems, rows = check(args.site_dir, args.url, timeout=args.timeout)
    lines = [
        f"Live site check of {args.url}: {'OK' if not problems else 'FAILED'}.",
        "",
        "| File | HTTP | Encoding | Bytes sent | Matches the deploy |",
        "| --- | ---: | --- | ---: | --- |",
        *rows,
        *(f"- **{p}**" for p in problems),
    ]
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write("\n".join(lines) + "\n")
    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
