#!/usr/bin/env bash
# Point current.env at an earlier release: the rollback. The host starts it at its next start, or
# now with scripts/deploy_release.sh. With no argument, lists the most recent releases.
#
#   LAKE_BUCKET=... scripts/promote_release.sh [image-commit]
set -euo pipefail

: "${LAKE_BUCKET:?set LAKE_BUCKET}"
prefix="s3://$LAKE_BUCKET/artifacts/releases"
if [ $# -eq 0 ]; then
  echo "current: $(aws s3 cp --only-show-errors "$prefix/current.env" - | sed -n 's/^AIRFLOW_IMAGE=.*://p')"
  aws s3 ls "$prefix/" | grep -v ' current.env$' | sort | tail -10
  exit 0
fi
[[ "$1" =~ ^[0-9a-f]{12}$ ]] || { echo "not a 12-character commit: $1" >&2; exit 2; }
aws s3 ls "$prefix/$1.env" >/dev/null || { echo "no release $1 at $prefix/" >&2; exit 1; }
aws s3 cp --only-show-errors "$prefix/$1.env" "$prefix/current.env"
echo "current release: $1"
