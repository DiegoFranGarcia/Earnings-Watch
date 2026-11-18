"""How far the image's Python is behind its newest release, from python.org's own list.

    python3 scripts/check_python_freshness.py <version in the image> <accepted file>

Neither Trivy nor pip-audit sees CPython itself (the base image builds it from source), nor the
libraries it bundles (expat, inside pyexpat). This fills that gap. It fails when a newer release
of the same minor version has been out for at least 14 days (the project's two-week rule: from
then on, it could be adopted), unless the accepted file lists this exact version, with a reason,
until a date that has not passed. Exits 1 if behind and not accepted, 2 if python.org's list or
the accepted file cannot be read.
"""

import datetime
import json
import re
import sys
import urllib.request

URL = "https://www.python.org/api/v2/downloads/release/?is_published=true"
WAIT_DAYS = 14
WARN_DAYS = 14


def releases(minor: str) -> dict[int, datetime.date]:
    """Patch number -> release date, for every final release of this minor version."""
    # URL is a fixed https address, never taken from input.
    with urllib.request.urlopen(URL, timeout=30) as response:  # noqa: S310
        data = json.load(response)
    found = {}
    for item in data:
        match = re.fullmatch(r"Python (\d+\.\d+)\.(\d+)", str(item.get("name", "")))
        if match and match[1] == minor and not item.get("pre_release"):
            found[int(match[2])] = datetime.date.fromisoformat(item["release_date"][:10])
    if not found:
        raise ValueError(f"no Python {minor} releases in python.org's list")
    return found


def accepted_versions(path: str) -> dict[str, tuple[datetime.date, str]]:
    """Version -> (until, reason), from lines 'version | until | reason'."""
    accepted = {}
    with open(path) as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 3 or not all(parts):
                raise ValueError(f"{path}:{number}: expected 'version | until | reason'")
            accepted[parts[0]] = (datetime.date.fromisoformat(parts[1]), parts[2])
    return accepted


def main() -> int:
    version, accepted_path = sys.argv[1:3]
    minor, patch = version.rsplit(".", 1)
    today = datetime.datetime.now(datetime.UTC).date()
    try:
        found = releases(minor)
        accepted = accepted_versions(accepted_path)
    except (OSError, ValueError, KeyError, TypeError) as error:
        sys.stderr.write(f"could not check the image's Python: {error}\n")
        return 2
    newest = max(found)
    print("### The image's Python")
    print()
    print(
        f"Python **{version}** in the image; the newest {minor} release is "
        f"**{minor}.{newest}** ({found[newest]})."
    )
    newer = sorted(p for p in found if p > int(patch))
    if not newer:
        print("\nUp to date.")
        return 0
    print()
    for p in newer:
        print(f"- {minor}.{p}: released {found[p]}, {(today - found[p]).days} days ago")
    if all((today - found[p]).days < WAIT_DAYS for p in newer):
        print(f"\nNewer releases are under {WAIT_DAYS} days old (the two-week rule): not due yet.")
        return 0
    if version in accepted:
        until, reason = accepted[version]
        if today <= until:
            print(f"\nBehind, and accepted until {until}: {reason}")
            if (until - today).days <= WARN_DAYS:
                notice = f"::warning::The acceptance of Python {version} ends on {until}"
                print(notice, file=sys.stderr)
            return 0
        print(f"\nThe acceptance of Python {version} ended on {until}.")
    print(
        f"\n**Behind**: a newer {minor} release has been out for {WAIT_DAYS} days or more. "
        f"Move to a base image with a newer Python, or accept {version} in {accepted_path} "
        "with a reason and a date."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
