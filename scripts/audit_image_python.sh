#!/usr/bin/env bash
# Audit both Python environments inside an image (Airflow's, and dbt's virtual environment) with
# scripts/audit_python.sh, against security/accepted-vulnerabilities.txt.
#
#   scripts/audit_image_python.sh <image>
#
# Both are audited even if the first fails; exits 1 if either does.
set -euo pipefail
image="${1:?usage: scripts/audit_image_python.sh <image>}"
root="$(git rev-parse --show-toplevel)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

docker run --rm --network none --entrypoint python "$image" -m pip freeze --all \
  | grep -v '^-e ' > "$work/airflow-env.txt"
docker run --rm --network none --entrypoint /opt/dbt_venv/bin/python "$image" -m pip freeze --all \
  | grep -v '^-e ' > "$work/dbt-env.txt"
status=0
"$root/scripts/audit_python.sh" "$work/airflow-env.txt" "the image's Airflow environment" || status=1
"$root/scripts/audit_python.sh" "$work/dbt-env.txt" "the image's dbt environment" || status=1
exit "$status"
