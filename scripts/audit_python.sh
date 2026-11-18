#!/usr/bin/env bash
# Audit a pinned package list (requirements format) with pip-audit 2.10.1, then judge the report
# against security/accepted-vulnerabilities.txt: any vulnerability not accepted there fails.
#
#   scripts/audit_python.sh <requirements-file> <label> [--strict]
#
# --strict (the scheduled scan) also fails on acceptances that expire within 14 days.
#
# pip-audit, and everything it installs, is resolved as of 15 days ago: the two-week rule applies
# to the scanner too. Exits 0 if every finding is accepted, 1 if not, 2 if no report was produced.
set -euo pipefail
list="${1:?usage: scripts/audit_python.sh <requirements-file> <label>}"
label="${2:?usage: scripts/audit_python.sh <requirements-file> <label>}"
strict="${3:-}"
[ -z "$strict" ] || [ "$strict" = --strict ] || { echo "unknown option: $strict" >&2; exit 2; }
root="$(git rev-parse --show-toplevel)"
cutoff="$(python3 -c 'import datetime as d; print((d.date.today() - d.timedelta(days=15)).isoformat())')"
report="$(mktemp)"; errors="$(mktemp)"
trap 'rm -f "$report" "$errors"' EXIT

# pip-audit exits 1 both when it finds vulnerabilities and when it fails: the report decides which.
# PyPI's answers for packages with thousands of releases (botocore, boto3) can take longer than
# pip-audit's default 15 seconds, so it gets 60, and one more try if it still produced no report.
# A retry cannot hide a vulnerability: a run that finds one always writes its report.
for attempt in 1 2; do
  uvx --exclude-newer "$cutoff" --from pip-audit==2.10.1 pip-audit -r "$list" --no-deps --disable-pip \
    --progress-spinner off --timeout 60 --format json >"$report" 2>"$errors" </dev/null || true
  if [ -s "$report" ]; then
    break
  fi
  if [ "$attempt" = 1 ]; then
    echo "pip-audit produced no report for $label (attempt 1); trying once more" >&2
  fi
done
if [ ! -s "$report" ]; then
  echo "pip-audit produced no report for $label:" >&2
  tail -20 "$errors" >&2
  exit 2
fi
python3 "$root/scripts/evaluate_audit.py" "$report" "$root/security/accepted-vulnerabilities.txt" "$label" \
  ${strict:+"$strict"}
