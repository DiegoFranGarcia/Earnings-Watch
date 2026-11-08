#!/usr/bin/env bash
# Run the DAG integrity tests inside the Airflow image, where Airflow, its providers and Cosmos
# are installed: the same image that runs the pipeline. Used locally and by CI.
#
#   docker build -t earnings-watch-airflow:test airflow
#   scripts/test_dags.sh earnings-watch-airflow:test
set -euo pipefail

image="${1:?usage: scripts/test_dags.sh <airflow-image>}"
cd "$(git rev-parse --show-toplevel)"

# The dbt DAG reads dbt's manifest while parsing, so the image's own dbt builds one first.
# pytest is installed into a scratch folder: test tooling never goes into the image itself.
docker run --rm \
  --user "$(id -u):0" \
  --volume "$PWD:/repo" \
  --workdir /repo \
  --env AIRFLOW__CORE__LOAD_EXAMPLES=false \
  --env DBT_PROJECT_DIR=/repo/dbt \
  --env PYTHONPATH=/tmp/test-libs:/repo/airflow/dags \
  --entrypoint bash \
  "$image" -c '
    set -euo pipefail
    /opt/dbt_venv/bin/dbt parse --project-dir dbt --profiles-dir dbt --quiet
    python -m pip install --quiet --no-cache-dir --target /tmp/test-libs "pytest==9.1.1"
    python -m pytest -q -p no:cacheprovider tests/dags
  '
