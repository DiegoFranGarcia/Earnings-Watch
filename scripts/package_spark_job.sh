#!/usr/bin/env bash
# Package the Spark job and upload it to s3://<bucket>/artifacts/spark/<git commit>/.
#
# Every upload is named after the commit it was built from, so any EMR run can be traced
# to its exact code. Refuses to package uncommitted changes, for the same reason.
#
#   scripts/package_spark_job.sh earnings-watch-dev-097040011808
set -euo pipefail

bucket="${1:?usage: scripts/package_spark_job.sh <lake-bucket>}"
cd "$(git rev-parse --show-toplevel)"

if [[ -n "$(git status --porcelain -- spark)" ]]; then
  echo "spark/ has uncommitted changes: commit first, so the upload matches a commit." >&2
  exit 1
fi

sha="$(git rev-parse --short=12 HEAD)"
out="build/spark/${sha}"
rm -rf "${out}"
mkdir -p "${out}"

# The zip must contain the lib/ folder itself, so `import lib.transforms` works on EMR.
(cd spark && zip -qr "../${out}/lib.zip" lib -x '*/__pycache__/*' '*.pyc')
cp spark/jobs/fsds_to_silver.py "${out}/"

if [[ "${bucket}" == "--local-only" ]]; then
  echo "${out}"
  exit 0
fi
aws s3 cp "${out}/" "s3://${bucket}/artifacts/spark/${sha}/" --recursive --only-show-errors
echo "${sha}"
