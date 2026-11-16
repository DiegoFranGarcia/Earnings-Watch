#!/usr/bin/env bash
# Boot the production stack from an image, exactly as the host will (the production Compose file,
# the same settings), check it, and tear it down. Fails if a service is unhealthy, a DAG fails to
# import, or the DAGs are not exactly the expected six. Nothing is shared with the local
# development stack (its own project name, database volume and port 8081).
#
#   scripts/smoke_test_prod_stack.sh <image>
#
# By default it uses the real configuration: Airflow's secrets from Secrets Manager, the Snowflake
# keys in ~/.snowflake/keys and settings from airflow/.env. With SMOKE_TEST_THROWAWAY=1 (as in CI)
# it generates throwaway keys, secrets and placeholder settings instead: nothing a smoke test checks
# connects to Snowflake, AWS or the SEC, so the image is tested just as well, with no real secret.
set -euo pipefail

image="${1:?usage: scripts/smoke_test_prod_stack.sh <image>}"
throwaway="${SMOKE_TEST_THROWAWAY:-0}"
expected_dags="company_tickers_snapshot dbt_build sec_daily_index sec_fsds_quarterly snowflake_load snowflake_load_daily_index"
cd "$(git rev-parse --show-toplevel)"

home="$(mktemp -d)"
trap 'docker compose -p ew-smoke -f deploy/compose.yaml --env-file "$home/airflow.env" down -v >/dev/null 2>&1; rm -rf "$home"' EXIT
mkdir -p "$home/logs" "$home/keys"
chmod 777 "$home/logs"

if [ "$throwaway" = 1 ]; then
  for key in svc_airflow_rsa_key svc_dbt_rsa_key; do
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$home/keys/$key.p8" 2>/dev/null
  done
  chmod 644 "$home"/keys/*.p8  # throwaway: readable by the containers' user, worthless to anyone
  internals() {
    python3 - <<'PY'
import base64, os, secrets
print("POSTGRES_PASSWORD=" + secrets.token_urlsafe(24))
print("FERNET_KEY=" + base64.urlsafe_b64encode(os.urandom(32)).decode())
print("AIRFLOW__API_AUTH__JWT_SECRET=" + secrets.token_urlsafe(32))
print("_AIRFLOW_WWW_USER_PASSWORD=" + secrets.token_urlsafe(16))
print("SEC_USER_AGENT=EarningsWatch smoke-test@example.com")
PY
  }
  setting() { echo "smoke-test-$1"; }
else
  cp ~/.snowflake/keys/svc_airflow_rsa_key.p8 ~/.snowflake/keys/svc_dbt_rsa_key.p8 "$home/keys/"
  internals() {
    aws secretsmanager get-secret-value --secret-id earningswatch/dev/airflow-internals \
      --query SecretString --output text \
      | python3 -c 'import json, sys; [print(f"{k}={v}") for k, v in json.load(sys.stdin).items()]'
  }
  setting() { grep "^$1=" airflow/.env | head -1 | cut -d= -f2-; }
fi

{
  echo "AIRFLOW_IMAGE=$image"
  echo "ENV_FILE_PATH=$home/airflow.env"
  echo "EARNINGSWATCH_HOME=$home"
  echo "KEYS_DIR=$home/keys"
  echo "API_PORT=8081"
  internals
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
"${compose[@]}" down -v >/dev/null 2>&1 || true  # a stack left by an interrupted run must not be reused
failures=0
fail() { echo "FAIL: $1" >&2; failures=$((failures + 1)); }

echo "starting the production stack from $image ($([ "$throwaway" = 1 ] && echo throwaway || echo real) configuration) ..."
if ! "${compose[@]}" up -d --wait --wait-timeout 300 >/dev/null; then
  "${compose[@]}" ps --format '{{.Service}}: {{.Status}}' >&2
  echo "FAIL: the stack did not become healthy" >&2
  exit 1
fi
"${compose[@]}" ps --format '{{.Service}}: {{.Status}}'

echo "--- import errors:"
errors="$("${compose[@]}" exec -T airflow-scheduler airflow dags list-import-errors -o plain 2>/dev/null || true)"
echo "$errors"
if echo "$errors" | grep -q '\.py'; then fail "a DAG file failed to import"; fi

echo "--- DAGs:"
dags="$("${compose[@]}" exec -T airflow-scheduler airflow dags list -o plain 2>/dev/null | awk 'NR > 1 {print $1}' | sort -u | tr '\n' ' ' | sed 's/ $//')"
echo "$dags"
if [ "$dags" != "$expected_dags" ]; then fail "expected exactly: $expected_dags"; fi

echo "--- baked in: the dbt manifest and the earningswatch package"
"${compose[@]}" exec -T airflow-scheduler bash -c \
  'ls -l /opt/airflow/dbt/target/manifest.json | awk "{print \$5, \"bytes\"}"; python -c "import earningswatch.volume; print(\"earningswatch importable\")"' \
  || fail "the manifest or the earningswatch package is missing"

echo "--- the API's health report, on 127.0.0.1:8081 only:"
health="$(curl -fsS http://127.0.0.1:8081/api/v2/monitor/health || echo '{}')"
echo "$health" | python3 -c '
import json, sys
health = json.load(sys.stdin)
statuses = {k: v.get("status") for k, v in health.items()}
print(statuses)
sys.exit(0 if statuses and all(s == "healthy" for s in statuses.values()) else 1)' \
  || fail "a component is not healthy"

if [ "$failures" -gt 0 ]; then
  echo "SMOKE TEST FAILED: $failures check(s)" >&2
  exit 1
fi
echo "SMOKE TEST PASSED"
