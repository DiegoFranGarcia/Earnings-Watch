"""The two-week rule (ADR 14) for the site's npm packages, every one in the lockfile.

Each package in site/package-lock.json must have been published at least 14 days before the
lockfile was last changed. Run in CI by the site check; locally:

    python3 scripts/check_npm_lock_age.py site/package-lock.json

To add or update packages within the rule, resolve as of a date 15 days ago:

    cd site && npm install --before="$(date -u -v-15d +%F)"    # macOS; GNU date: -d '15 days ago'
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MIN_AGE = dt.timedelta(days=14)
REGISTRY = "https://registry.npmjs.org"


def git(*args: str) -> str:
    """git's output; fixed arguments and git from PATH, as everywhere this runs (CI, a Mac)."""
    result = subprocess.run(["git", *args], capture_output=True, text=True)  # noqa: S603, S607
    return result.stdout.strip()


def lockfile_changed_at(lockfile: Path) -> dt.datetime:
    """When the lockfile was last committed; now, if it has uncommitted changes or no history."""
    last_commit = git("log", "-1", "--format=%cI", "--", str(lockfile))
    if git("status", "--porcelain", "--", str(lockfile)) or not last_commit:
        return dt.datetime.now(dt.UTC)
    return dt.datetime.fromisoformat(last_commit)


def packages(lockfile: Path) -> set[tuple[str, str]]:
    lock = json.loads(lockfile.read_text())
    return {
        (key.rsplit("node_modules/", 1)[-1], meta["version"])
        for key, meta in lock["packages"].items()
        if key and "version" in meta and not meta.get("link")
    }


def published(name: str, version: str) -> dt.datetime | None:
    with urllib.request.urlopen(f"{REGISTRY}/{name.replace('/', '%2F')}", timeout=30) as response:  # noqa: S310
        when = json.load(response).get("time", {}).get(version)
    return dt.datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None


def main(lockfile: Path) -> int:
    changed = lockfile_changed_at(lockfile)
    cutoff = changed - MIN_AGE
    pinned = sorted(packages(lockfile))
    with ThreadPoolExecutor(max_workers=16) as pool:
        dates = list(pool.map(lambda p: published(*p), pinned))
    too_new = [
        (n, v, d) for (n, v), d in zip(pinned, dates, strict=True) if d is None or d > cutoff
    ]
    print(
        f"{len(pinned)} packages; lockfile changed {changed:%Y-%m-%d}; "
        f"each must predate {cutoff:%Y-%m-%d}"
    )
    for name, version, when in too_new:
        print(
            f"  TOO NEW: {name}@{version} published {when:%Y-%m-%d}"
            if when
            else f"  UNKNOWN: {name}@{version}"
        )
    return 1 if too_new else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "site/package-lock.json")))
