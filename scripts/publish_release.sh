#!/usr/bin/env bash
# Publish a release: the image and Spark code the Airflow host should run. Checks both exist,
# writes artifacts/releases/<image commit>.env once (S3 refuses to overwrite it, so history cannot
# be rewritten), then copies it to artifacts/releases/current.env, which the host reads at every
# start. Writing the record before the pointer means the pointer only ever names a whole release.
#
#   LAKE_BUCKET=... ECR_REPOSITORY=... scripts/publish_release.sh [image-commit] [spark-commit]
#
# Both commits default to HEAD (12 characters). Prints the release on success.
set -euo pipefail

: "${LAKE_BUCKET:?set LAKE_BUCKET}" "${ECR_REPOSITORY:?set ECR_REPOSITORY}"
cd "$(git rev-parse --show-toplevel)"
image_commit="${1:-$(git rev-parse --short=12 HEAD)}"
spark_commit="${2:-$image_commit}"
for c in "$image_commit" "$spark_commit"; do
  [[ "$c" =~ ^[0-9a-f]{12}$ ]] || { echo "not a 12-character commit: $c" >&2; exit 2; }
done
image="$ECR_REPOSITORY:$image_commit"
spark="s3://$LAKE_BUCKET/artifacts/spark/$spark_commit"

aws ecr describe-images --repository-name "${ECR_REPOSITORY#*/}" \
  --image-ids "imageTag=$image_commit" >/dev/null \
  || { echo "no such image in ECR: $image" >&2; exit 1; }
[ -n "$(aws s3 ls "$spark/")" ] || { echo "no Spark code at $spark/" >&2; exit 1; }

record="artifacts/releases/$image_commit.env"
body="$(mktemp)"
trap 'rm -f "$body"' EXIT
printf 'AIRFLOW_IMAGE=%s\nSPARK_CODE_URI=%s\n' "$image" "$spark" > "$body"
if [ -n "${GITHUB_RUN_ID:-}" ]; then
  published_by="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
else
  published_by="${USER:-unknown} (by hand)"
fi
{
  echo "GIT_COMMIT=$image_commit"
  echo "PUBLISHED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "PUBLISHED_BY=$published_by"
} >> "$body"

if ! aws s3api put-object --bucket "$LAKE_BUCKET" --key "$record" --body "$body" \
    --if-none-match '*' >/dev/null 2>&1; then
  # Already published: fine if it names the same image and Spark code, refused otherwise.
  existing="$(aws s3 cp --only-show-errors "s3://$LAKE_BUCKET/$record" -)"
  if [ "$(echo "$existing" | grep -E '^(AIRFLOW_IMAGE|SPARK_CODE_URI)=')" \
      != "$(grep -E '^(AIRFLOW_IMAGE|SPARK_CODE_URI)=' "$body")" ]; then
    echo "a different release is already published as $record; refusing to rewrite it" >&2
    exit 1
  fi
  echo "already published: $record" >&2
fi

aws s3 cp --only-show-errors "s3://$LAKE_BUCKET/$record" \
  "s3://$LAKE_BUCKET/artifacts/releases/current.env"
echo "current release: $image with $spark"
