"""Judge a pip-audit JSON report against the accepted vulnerabilities, and fail on anything else.

    python3 scripts/evaluate_audit.py <report.json> <accepted.txt> <label> [--strict]

The accepted file lists one vulnerability per line, "ID | package | expires | reason". A
vulnerability is accepted only by its own ID, for that package, until its expiry date: from then
on it fails again, and someone has to look at it once more. An expiry more than 180 days away is
refused. Acceptances used by this report that expire within 14 days are warnings; with --strict
(the scheduled scan) they fail, so they reach someone. Exits 1 if any finding is not accepted
(or, with --strict, on a warning), 2 if the report or the accepted list cannot be read.
"""

import datetime
import json
import sys

MAX_DAYS = 180
WARN_DAYS = 14


def accepted_ids(path: str, today: datetime.date) -> dict[str, tuple[str, datetime.date, str]]:
    """ID -> (package, expires, reason), from the accepted file; comments and blanks skipped."""
    accepted = {}
    with open(path) as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 4 or not all(parts):
                raise ValueError(f"{path}:{number}: expected 'ID | package | expires | reason'")
            try:
                expires = datetime.date.fromisoformat(parts[2])
            except ValueError:
                raise ValueError(
                    f"{path}:{number}: '{parts[2]}' is not a date (YYYY-MM-DD)"
                ) from None
            if (expires - today).days > MAX_DAYS:
                raise ValueError(f"{path}:{number}: expires {expires}, over {MAX_DAYS} days away")
            accepted[parts[0]] = (parts[1].lower(), expires, parts[3])
    return accepted


def main() -> int:
    strict = "--strict" in sys.argv[1:]
    report_path, accepted_path, label = [arg for arg in sys.argv[1:] if arg != "--strict"][:3]
    today = datetime.datetime.now(datetime.UTC).date()
    try:
        with open(report_path) as handle:
            report = json.load(handle)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"could not read the pip-audit report: {error}\n")
        return 2
    try:
        accepted = accepted_ids(accepted_path, today)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"could not read the accepted vulnerabilities: {error}\n")
        return 2
    findings, unaccepted, warnings = 0, [], []
    accepted_here: dict[str, list[str]] = {}
    for package in report["dependencies"]:
        for vuln in package.get("vulns", []):
            findings += 1
            name = package["name"].lower()
            entry = accepted.get(vuln["id"])
            if entry and entry[0] == name and today < entry[1]:
                accepted_here.setdefault(name, []).append(vuln["id"])
                if (entry[1] - today).days <= WARN_DAYS:
                    warnings.append(f"{vuln['id']} ({name}) is accepted only until {entry[1]}")
                continue
            fixes = ", ".join(vuln.get("fix_versions", [])) or "no fix yet"
            expired = f"; its acceptance ended on {entry[1]}" if entry and entry[0] == name else ""
            unaccepted.append(
                f"{package['name']} {package['version']}: {vuln['id']} (fixed in: {fixes}){expired}"
            )
    total = len(report["dependencies"])
    sys.stdout.write(
        f"{label}: {total} packages, {findings} finding(s), "
        f"{findings - len(unaccepted)} accepted, {len(unaccepted)} not accepted\n"
    )
    for name, ids in sorted(accepted_here.items()):
        _, expires, reason = accepted[ids[0]]
        sys.stdout.write(f"  accepted: {name} ({len(ids)}, until {expires}): {reason}\n")
    for line in unaccepted:
        sys.stdout.write(f"  NOT ACCEPTED: {line}\n")
    for line in warnings:
        sys.stdout.write(f"  warning: {line}\n")
        sys.stderr.write(f"::warning::{label}: {line}\n")
    return 1 if unaccepted or (strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
