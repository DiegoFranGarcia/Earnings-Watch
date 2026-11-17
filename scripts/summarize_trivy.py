"""Summarise a Trivy JSON report as Markdown: findings by severity, and the packages with most.

    python3 scripts/summarize_trivy.py <trivy.json>

Report only: always exits 0 when the report can be read. The image's operating-system packages
are scanned here; Python packages are judged by pip-audit (scripts/audit_python.sh), which blocks.
"""

import json
import sys
from collections import Counter

with open(sys.argv[1]) as handle:
    report = json.load(handle)
vulns = [v for result in report.get("Results") or [] for v in result.get("Vulnerabilities") or []]
by_severity = Counter(v.get("Severity", "UNKNOWN") for v in vulns)
fixable = sum(1 for v in vulns if v.get("FixedVersion"))
by_package = Counter(f"{v.get('PkgName')} {v.get('InstalledVersion')}" for v in vulns)

print("### Operating-system vulnerabilities in the image (Trivy, report only)")
print()
if not vulns:
    print("No known vulnerabilities in the image's operating-system packages.")
    sys.exit(0)
print(f"**{len(vulns)}** finding(s), **{fixable}** with a fixed version available.")
print()
print("| Severity | Findings |")
print("|---|---|")
for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"):
    if by_severity.get(severity):
        print(f"| {severity} | {by_severity[severity]} |")
if by_package:
    print()
    print("| Package | Findings |")
    print("|---|---|")
    for package, count in by_package.most_common(10):
        print(f"| `{package}` | {count} |")
