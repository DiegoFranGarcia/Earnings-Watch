#!/usr/bin/env bash
# Boot the production stack on this machine, from an image in ECR, exactly as the host will:
# the production Compose file, Airflow's secrets from Secrets Manager, the same settings. Then
# check it and tear it down. Nothing is shared with the local development stack (its own project
# name, database volume and port 8081).
#
#   scripts/smoke_test_prod_stack.sh <image>
set -euo pipefail

image="${1:?usage: scripts/smoke_test_prod_stack.sh <image>}"
cd "$(git rev-parse --show-toplevel)"

home="$(mktemp -d)"
trap 'docker compose -p ew-smoke -f deploy/compose.yaml --env-file "$home/airflow.env" down -v >/dev/null 2>&1; rm -rf "$home"' EXIT
mkdir -p "$home/logs" "$home/keys"
chmod 777 "$home/logs"
cp ~/.snowflake/keys/svc_airflow_rsa_key.p8 ~/.snowflake/keys/svc_dbt_rsa_key.p8 "$home/keys/"

setting() { grep "^$1=" airflow/.env | head -1 | cut -d= -f2-; }
{
  echo "AIRFLOW_IMAGE=$image"
  echo "ENV_FILE_PATH=$home/airflow.env"
  echo "EARNINGSWATCH_HOME=$home"
  echo "KEYS_DIR=$home/keys"
  echo "API_PORT=8081"
  aws secretsmanager get-secret-value --secret-id earningswatch/dev/airflow-internals \
    --query SecretString --output text \
    | python3 -c 'import json, sys; [print(f"{k}={v}") for k, v in json.load(sys.stdin).items()]'
  echo "DISCORD_WEBHOOK_URL="  # the smoke test must never page anyone
  for name in LAKE_BUCKET EMR_APPLICATION_ID EMR_JOB_ROLE_ARN SPARK_CODE_URI SF_ACCOUNT SF_DATABASE; do
    echo "$name=$(setting "$name")"
  done
  echo "SF_USER=SVC_AIRFLOW"
  echo "SF_PRIVATE_KEY_PATH=/opt/airflow/keys/svc_airflow_rsa_key.p8"
  echo "DBT_SNOWFLAKE_PRIVATE_KEY_PATH=/opt/airflow/keys/svc_dbt_rsa_key.p8"
} > "$home/airflow.env"
chmod 600 "$home/airflow.env"

compose=(docker compose -p ew-smoke -f deploy/compose.yaml --env-file "$home/airflow.env")
echo "starting the production stack from $image ..."
"${compose[@]}" up -d --wait --wait-timeout 300 >/dev/null
"${compose[@]}" ps --format '{{.Service}}: {{.Status}}'

echo "--- import errors:"
"${compose[@]}" exec -T airflow-scheduler airflow dags list-import-errors 2>/dev/null | tail -n +1
echo "--- DAGs:"
"${compose[@]}" exec -T airflow-scheduler airflow dags list -o plain 2>/dev/null | awk 'NR > 1 {print $1}' | sort -u
echo "--- baked in: the dbt manifest and the earningswatch package"
"${compose[@]}" exec -T airflow-scheduler bash -c \
  'ls -l /opt/airflow/dbt/target/manifest.json | awk "{print \$5, \"bytes\"}"; python -c "import earningswatch.volume; print(\"earningswatch importable\")"'
echo "--- the API, on 127.0.0.1:8081 only:"
curl -s http://127.0.0.1:8081/api/v2/monitor/health | python3 -c 'import json, sys; h = json.load(sys.stdin); print({k: v.get("status") for k, v in h.items()})'
