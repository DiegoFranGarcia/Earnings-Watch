#!/usr/bin/env bash
# Build the production Airflow image and push it to ECR, tagged with the last commit that changed
# anything the image contains (airflow/, dbt/, deploy/). A commit that changes none of them
# reuses the existing image. Prints the image (repository:commit) on its last line.
#
#   scripts/build_airflow_image.sh <ecr-repository-url>
#
# Refuses uncommitted changes to anything the image contains, so every image matches a commit.
# Tags are immutable in ECR, so a commit that was already pushed is not built again.
set -euo pipefail

repository="${1:?usage: scripts/build_airflow_image.sh <ecr-repository-url>}"
cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain -- airflow dbt deploy)" ]; then
  echo "commit airflow/, dbt/ and deploy/ first: the image must match a commit" >&2
  exit 1
fi

commit="$(git log -1 --format=%H -- airflow dbt deploy | cut -c1-12)"
image="$repository:$commit"
registry="${repository%%/*}"
name="${repository#*/}"

if aws ecr describe-images --repository-name "$name" --image-ids "imageTag=$commit" \
    >/dev/null 2>&1; then
  echo "already in ECR: $image" >&2
  echo "$image"
  exit 0
fi

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "$registry" >&2
docker build --platform linux/arm64 -t "earnings-watch-airflow:base-$commit" airflow >&2
docker build --platform linux/arm64 -f airflow/Dockerfile.prod \
  --build-arg BASE_IMAGE="earnings-watch-airflow:base-$commit" -t "$image" . >&2
docker push "$image" >&2
echo "$image"
