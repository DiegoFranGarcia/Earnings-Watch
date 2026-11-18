"""The gate on the images' operating-system vulnerabilities, and its Markdown summary.

    python3 scripts/trivy_gate.py <ignore file> <label>=<trivy.json> [<label>=<trivy.json> ...]

Each report comes from `trivy image --format json --show-suppressed --ignorefile <ignore file>`:
Trivy applies the accepted findings itself (by ID and package, until their expiry date), and
this script decides. It fails when:
  - a report still has a fixable CRITICAL or HIGH finding (unfixed ones cannot be acted on, and
    were read once when the gate was introduced), or
  - the ignore file breaks its own rules: every entry names its packages, says why, and expires
    no more than 180 days from today.
Entries that no longer match anything, and entries expiring within 14 days, are warnings; with
--strict (the scheduled scan), warnings fail too, so they reach someone.
Exit status 0 means the images may ship.
"""

import datetime
import json
import re
import sys
from collections import Counter

BLOCKING = ("CRITICAL", "HIGH")
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
MAX_DAYS = 180
WARN_DAYS = 14


def read_ignore_file(path):
    """The entries of the ignore file, read strictly: a line this does not expect is an error."""
    entries, errors = [], []
    patterns = {
        "id": re.compile(r"^  - id: (\S+)$"),
        "purls": re.compile(r"^    purls:$"),
        "purl": re.compile(r"^      - (pkg:\S+)$"),
        "statement": re.compile(r'^    statement: "([^"]+)"$'),
        "expired_at": re.compile(r"^    expired_at: (\d{4}-\d{2}-\d{2})$"),
    }
    with open(path) as handle:
        lines = handle.read().splitlines()
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#") or line == "vulnerabilities:":
            continue
        kind, match = next(
            ((k, p.match(line)) for k, p in patterns.items() if p.match(line)), (None, None)
        )
        if kind == "id":
            entries.append({"id": match[1], "purls": [], "line": number})
        elif kind is None or not entries:
            errors.append(f"{path}:{number}: unexpected line: {line.strip()}")
        elif kind == "purl":
            entries[-1]["purls"].append(match[1])
        elif kind in ("statement", "expired_at"):
            entries[-1][kind] = match[1]
    today = datetime.datetime.now(datetime.UTC).date()
    for entry in entries:
        where = f"{path}:{entry['line']} ({entry['id']})"
        if not entry["purls"]:
            errors.append(f"{where}: no purls; an entry must name its packages")
        if not entry.get("statement"):
            errors.append(f"{where}: no statement; an entry must say why it is accepted")
        if not entry.get("expired_at"):
            errors.append(f"{where}: no expired_at; every acceptance expires")
            continue
        expiry = datetime.date.fromisoformat(entry["expired_at"])
        entry["expiry"] = expiry
        if (expiry - today).days > MAX_DAYS:
            errors.append(f"{where}: expires {expiry}, more than {MAX_DAYS} days away")
    return entries, errors


def main():
    strict = "--strict" in sys.argv[1:]
    arguments = [arg for arg in sys.argv[1:] if arg != "--strict"]
    ignore_path, reports = arguments[0], [arg.split("=", 1) for arg in arguments[1:]]
    entries, errors = read_ignore_file(ignore_path)
    today = datetime.datetime.now(datetime.UTC).date()
    suppressed_ids, blocking, warnings = set(), [], []

    print("### Operating-system vulnerabilities in the images (Trivy)")
    for label, path in reports:
        with open(path) as handle:
            report = json.load(handle)
        results = report.get("Results") or []
        vulns = [v for r in results for v in r.get("Vulnerabilities") or []]
        suppressed = [
            m["Finding"]
            for r in results
            for m in r.get("ExperimentalModifiedFindings") or []
            if m.get("Type") == "vulnerability" and m.get("Status") == "ignored"
        ]
        suppressed_ids |= {f["VulnerabilityID"] for f in suppressed}
        fixable = [v for v in vulns if v.get("FixedVersion")]
        stops = [v for v in fixable if v.get("Severity") in BLOCKING]
        blocking += [(label, v) for v in stops]
        everything = Counter(v.get("Severity") for v in vulns)
        can_fix = Counter(v.get("Severity") for v in fixable)
        print(
            f"\n**{label}** (`{report.get('ArtifactName', '?')}`): {len(vulns)} finding(s), "
            f"{len(fixable)} fixable, {len(suppressed)} accepted, **{len(stops)} blocking**.\n"
        )
        if not vulns:
            print("No findings left to show.")
            continue
        print("| Severity | Findings | Fixable |")
        print("|---|---|---|")
        for severity in SEVERITIES:
            if everything.get(severity):
                print(f"| {severity} | {everything[severity]} | {can_fix.get(severity, 0)} |")

    for entry in entries:
        expiry = entry.get("expiry")
        if expiry and expiry < today:
            warnings.append(f"{entry['id']} expired on {expiry}: it blocks again if still present")
        elif entry["id"] not in suppressed_ids:
            warnings.append(f"{entry['id']} matches nothing any more: remove it from {ignore_path}")
        elif expiry and (expiry - today).days <= WARN_DAYS:
            warnings.append(f"{entry['id']} expires on {expiry}: re-review it")

    if blocking:
        print("\n#### Blocking: fixable, CRITICAL or HIGH, not accepted\n")
        print("| Image | Severity | Package | Finding | Installed | Fixed in | Title |")
        print("|---|---|---|---|---|---|---|")
        order = {s: i for i, s in enumerate(SEVERITIES)}
        for label, v in sorted(blocking, key=lambda item: (item[0], order[item[1]["Severity"]])):
            title = (v.get("Title") or "").replace("|", "/")[:80]
            print(
                f"| {label} | {v['Severity']} | `{v['PkgName']}` | {v['VulnerabilityID']} | "
                f"{v.get('InstalledVersion')} | {v.get('FixedVersion')} | {title} |"
            )
        print(
            "\nFix it (a newer base image, or removing the package), or accept it in "
            f"`{ignore_path}` with the reason it cannot be reached and an expiry date."
        )
    if errors or warnings:
        print("\n#### The accepted list\n")
        for line in errors:
            print(f"- **error**: {line}")
        for line in warnings:
            print(f"- warning: {line}")
    for line in errors:
        print(f"::error::{line}", file=sys.stderr)
    for line in warnings:
        print(f"::warning::{line}", file=sys.stderr)
    failed = bool(blocking or errors or (strict and warnings))
    verdict = "fails" if failed else "passes"
    print(
        f"\nThe gate **{verdict}**: {len(blocking)} blocking finding(s), {len(errors)} error(s) "
        f"in the accepted list, {len(warnings)} warning(s)."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
