"""Judge a pip-audit JSON report against the accepted vulnerabilities, and fail on anything else.

    python3 scripts/evaluate_audit.py <report.json> <accepted.txt> <label>

The accepted file lists one vulnerability per line, "ID | package | reason". A vulnerability is
accepted only by its own ID: a new vulnerability in an accepted package still fails. Exits 1 if
any finding is not accepted, 2 if the report or the accepted list cannot be read.
"""

import json
import sys


def accepted_ids(path: str) -> dict[str, tuple[str, str]]:
    """ID -> (package, reason), from the accepted file; comments and blank lines are skipped."""
    accepted = {}
    with open(path) as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 3 or not all(parts):
                sys.exit(f"{path}:{number}: expected 'ID | package | reason', got: {line}")
            accepted[parts[0]] = (parts[1].lower(), parts[2])
    return accepted


def main() -> int:
    report_path, accepted_path, label = sys.argv[1:4]
    try:
        with open(report_path) as handle:
            report = json.load(handle)
    except (OSError, ValueError) as error:
        sys.stderr.write(f"could not read the pip-audit report: {error}\n")
        return 2
    try:
        accepted = accepted_ids(accepted_path)
    except OSError as error:
        sys.stderr.write(f"could not read the accepted vulnerabilities: {error}\n")
        return 2
    findings, unaccepted = 0, []
    accepted_here: dict[str, int] = {}
    for package in report["dependencies"]:
        for vuln in package.get("vulns", []):
            findings += 1
            name = package["name"].lower()
            if vuln["id"] in accepted and accepted[vuln["id"]][0] == name:
                accepted_here[name] = accepted_here.get(name, 0) + 1
            else:
                fixes = ", ".join(vuln.get("fix_versions", [])) or "no fix yet"
                unaccepted.append(
                    f"{package['name']} {package['version']}: {vuln['id']} (fixed in: {fixes})"
                )
    total = len(report["dependencies"])
    sys.stdout.write(
        f"{label}: {total} packages, {findings} finding(s), "
        f"{findings - len(unaccepted)} accepted, {len(unaccepted)} not accepted\n"
    )
    for name, count in sorted(accepted_here.items()):
        reason = next(r for _, (p, r) in accepted.items() if p == name)
        sys.stdout.write(f"  accepted: {name} ({count}): {reason}\n")
    for line in unaccepted:
        sys.stdout.write(f"  NOT ACCEPTED: {line}\n")
    return 1 if unaccepted else 0


if __name__ == "__main__":
    sys.exit(main())
