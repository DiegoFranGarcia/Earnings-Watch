"""The gate on Trivy's findings, for images and for Terraform, and its Markdown summary.

    python3 scripts/trivy_gate.py [--strict] <ignore file> <label>=<trivy.json> [...]

Each report is Trivy JSON with the ignore file already applied and the suppressed findings shown
(`trivy image --show-suppressed --ignorefile ...`, or `trivy convert --show-suppressed ...` for
`trivy config`): Trivy matches the accepted findings itself (by ID, package or path, until their
expiry date), and this script decides. It fails when:
  - a report still has a CRITICAL or HIGH finding that can be acted on: a vulnerability with a
    fixed version, or a failed Terraform check (unfixed vulnerabilities cannot be acted on, and
    were read once when the gate was introduced; see ADR 15), or
  - the ignore file breaks its own rules: every entry says why, names its packages (purls) or
    files (paths), and expires no more than 180 days from today.
Entries that no longer match anything, and entries expiring within 14 days, are warnings; with
--strict (the scheduled scan), warnings fail too, so they reach someone.
Exit status 0 means the gate passes.
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
SCOPE = {"vulnerabilities": "purls", "misconfigurations": "paths"}
PATTERNS = {
    "section": re.compile(r"^(vulnerabilities|misconfigurations):$"),
    "id": re.compile(r"^  - id: (\S+)$"),
    "list": re.compile(r"^    (purls|paths):$"),
    "purl": re.compile(r"^      - (pkg:\S+)$"),
    "path": re.compile(r'^      - "([^"]+)"$'),
    "statement": re.compile(r'^    statement: "([^"]+)"$'),
    "expired_at": re.compile(r"^    expired_at: (\d{4}-\d{2}-\d{2})$"),
}


def today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()


def read_ignore_file(path):
    """The entries of the ignore file, read strictly: a line this does not expect is an error."""
    entries, errors, section = [], [], None
    with open(path) as handle:
        lines = handle.read().splitlines()
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        kind, match = next(
            ((k, p.match(line)) for k, p in PATTERNS.items() if p.match(line)), (None, None)
        )
        if kind == "section":
            section = match[1]
        elif kind == "id" and section:
            entries.append({"id": match[1], "section": section, "scope": [], "line": number})
        elif kind is None or not entries:
            errors.append(f"{path}:{number}: unexpected line: {line.strip()}")
        elif kind == "list" and match[1] != SCOPE[entries[-1]["section"]]:
            errors.append(
                f"{path}:{number}: {entries[-1]['section']} are scoped by "
                f"{SCOPE[entries[-1]['section']]}, not {match[1]}"
            )
        elif kind in ("purl", "path"):
            entries[-1]["scope"].append(match[1])
        elif kind in ("statement", "expired_at"):
            entries[-1][kind] = match[1]
    for entry in entries:
        where = f"{path}:{entry['line']} ({entry['id']})"
        if not entry["scope"]:
            errors.append(
                f"{where}: no {SCOPE[entry['section']]}; an entry must say where it applies"
            )
        if not entry.get("statement"):
            errors.append(f"{where}: no statement; an entry must say why it is accepted")
        if not entry.get("expired_at"):
            errors.append(f"{where}: no expired_at; every acceptance expires")
            continue
        entry["expiry"] = datetime.date.fromisoformat(entry["expired_at"])
        if (entry["expiry"] - today()).days > MAX_DAYS:
            errors.append(f"{where}: expires {entry['expiry']}, more than {MAX_DAYS} days away")
    return entries, errors


def findings(report):
    """(blocking findings, counts for the summary, suppressed IDs) for one report."""
    results = report.get("Results") or []
    vulns = [v for r in results for v in r.get("Vulnerabilities") or []]
    checks = [
        (r.get("Target", "?"), m)
        for r in results
        for m in r.get("Misconfigurations") or []
        if m.get("Status") == "FAIL"
    ]
    suppressed = set()
    for r in results:
        for item in r.get("ExperimentalModifiedFindings") or []:
            if item.get("Status") != "ignored":
                continue
            finding = item.get("Finding") or {}
            suppressed.add(finding.get("VulnerabilityID") or finding.get("ID"))
    blocking = []
    for v in vulns:
        if v.get("FixedVersion") and v.get("Severity") in BLOCKING:
            blocking.append(
                (
                    v["Severity"],
                    f"`{v['PkgName']}`",
                    v["VulnerabilityID"],
                    f"{v.get('InstalledVersion')} → {v.get('FixedVersion')}",
                    v.get("Title"),
                )
            )
    for target, m in checks:
        if m.get("Severity") in BLOCKING:
            cause = m.get("CauseMetadata") or {}
            blocking.append(
                (
                    m["Severity"],
                    f"`{target}:{cause.get('StartLine', '?')}`",
                    m["ID"],
                    cause.get("Resource") or "",
                    m.get("Title"),
                )
            )
    if checks or any("Misconfigurations" in r for r in results):
        counts = {"kind": "config", "all": Counter(m.get("Severity") for _, m in checks)}
    else:
        counts = {
            "kind": "image",
            "all": Counter(v.get("Severity") for v in vulns),
            "fixable": Counter(v.get("Severity") for v in vulns if v.get("FixedVersion")),
        }
    return blocking, counts, suppressed


def summary_table(counts):
    if counts["kind"] == "config":
        rows = [(s, counts["all"][s]) for s in SEVERITIES if counts["all"].get(s)]
        return ["| Severity | Failed checks |", "|---|---|"] + [f"| {s} | {n} |" for s, n in rows]
    rows = [
        (s, counts["all"][s], counts["fixable"].get(s, 0))
        for s in SEVERITIES
        if counts["all"].get(s)
    ]
    return ["| Severity | Findings | Fixable |", "|---|---|---|"] + [
        f"| {s} | {n} | {f} |" for s, n, f in rows
    ]


def main():
    strict = "--strict" in sys.argv[1:]
    arguments = [arg for arg in sys.argv[1:] if arg != "--strict"]
    ignore_path, reports = arguments[0], [arg.split("=", 1) for arg in arguments[1:]]
    entries, errors = read_ignore_file(ignore_path)
    suppressed_ids, blocking, warnings = set(), [], []

    print("### Trivy findings")
    for label, path in reports:
        with open(path) as handle:
            report = json.load(handle)
        found, counts, suppressed = findings(report)
        suppressed_ids |= suppressed
        blocking += [(label, *item) for item in found]
        print(
            f"\n**{label}** (`{report.get('ArtifactName', '?')}`): {sum(counts['all'].values())} "
            f"finding(s), {len(suppressed)} accepted, **{len(found)} blocking**.\n"
        )
        table = summary_table(counts)
        print("\n".join(table) if len(table) > 2 else "No findings left to show.")

    for entry in entries:
        expiry = entry.get("expiry")
        if expiry and expiry < today():
            warnings.append(f"{entry['id']} expired on {expiry}: it blocks again if still present")
        elif entry["id"] not in suppressed_ids:
            warnings.append(f"{entry['id']} matches nothing any more: remove it from {ignore_path}")
        elif expiry and (expiry - today()).days <= WARN_DAYS:
            warnings.append(f"{entry['id']} expires on {expiry}: re-review it")

    if blocking:
        order = {s: i for i, s in enumerate(SEVERITIES)}
        print("\n#### Blocking: CRITICAL or HIGH, actionable, not accepted\n")
        print("| Report | Severity | Where | Finding | Detail | Title |")
        print("|---|---|---|---|---|---|")
        for label, severity, where, finding, detail, title in sorted(
            blocking, key=lambda item: (item[0], order[item[1]])
        ):
            title = (title or "").replace("|", "/")[:80]
            print(f"| {label} | {severity} | {where} | {finding} | {detail} | {title} |")
        print(
            f"\nFix it, or accept it in `{ignore_path}` with the reason it cannot be reached or "
            "is by design, and an expiry date."
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
