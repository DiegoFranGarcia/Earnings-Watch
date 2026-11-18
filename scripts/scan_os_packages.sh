#!/usr/bin/env bash
# Scan the operating-system packages of both images production runs with Trivy 0.76.1 (downloaded
# and checksum-verified on every run), and gate on the result with scripts/trivy_gate.py: fixable
# CRITICAL and HIGH findings fail, except those accepted in security/trivyignore.yaml.
#
#   scripts/scan_os_packages.sh <airflow image> [--strict]
#
# The Postgres image is the one pinned in deploy/compose.yaml. --strict also fails on warnings
# (accepted entries that match nothing, or expire within 14 days); the scheduled scan uses it, so
# they reach someone. Prints a Markdown summary. Linux only, on the CI runners.
set -euo pipefail
image="${1:?usage: scripts/scan_os_packages.sh <airflow image> [--strict]}"
shift
cd "$(git rev-parse --show-toplevel)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

case "$(uname -s)/$(uname -m)" in
  Linux/aarch64) asset=Linux-ARM64 sum=e174dff2a6dba5e3ae41f8d0537a6324405bd08132497340304c6b20e0f16a1f ;;
  Linux/x86_64) asset=Linux-64bit sum=c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0 ;;
  *) echo "no pinned Trivy for $(uname -s)/$(uname -m)" >&2; exit 2 ;;
esac
curl -fsSL -o "$work/trivy.tgz" \
  "https://github.com/aquasecurity/trivy/releases/download/v0.76.1/trivy_0.76.1_${asset}.tar.gz"
echo "$sum  $work/trivy.tgz" | sha256sum -c --quiet - >&2
tar -xzf "$work/trivy.tgz" -C "$work" trivy

postgres="$(sed -nE 's/^[[:space:]]*image:[[:space:]]*(postgres:[^ ]+).*/\1/p' deploy/compose.yaml)"
[[ "$postgres" == postgres:*@sha256:* ]] || { echo "no pinned Postgres image in compose.yaml" >&2; exit 2; }
for target in "airflow=$image" "postgres=$postgres"; do
  "$work/trivy" image --quiet --scanners vuln --pkg-types os --show-suppressed \
    --ignorefile security/trivyignore.yaml --format json \
    --output "$work/${target%%=*}.json" "${target#*=}"
done
python3 scripts/trivy_gate.py "$@" security/trivyignore.yaml \
  "Airflow image=$work/airflow.json" "Postgres image=$work/postgres.json"
