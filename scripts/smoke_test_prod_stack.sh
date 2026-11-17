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

# Nothing here reads the caller's standard input. Closing it means a command that forwards
# input (docker compose exec does) can never swallow the rest of a script that runs this one
# from a pipe or heredoc. Commands that need input get it from an explicit < redirect.
exec </dev/null

image="${1:?usage: scripts/smoke_test_prod_stack.sh <image>}"
throwaway="${SMOKE_TEST_THROWAWAY:-0}"
expected_dags="company_tickers_snapshot dbt_build sec_daily_index sec_fsds_quarterly snowflake_load snowflake_load_daily_index"
cd "$(git rev-parse --show-toplevel)"

home="$(mktemp -d)"
# Cleanup is best effort and never changes the result: the test's own exit status is kept. The
# containers write logs as their own user (50000), which a Linux runner cannot delete, so those are
# removed from inside a container running as root, using the image that is already here.
cleanup() {
  if [ "${SMOKE_TEST_KEEP:-0}" = 1 ]; then  # for debugging: leave the stack running to inspect
    echo "keeping the ew-smoke stack; remove it with:" >&2
    echo "  docker compose -p ew-smoke -f deploy/compose.yaml --env-file $home/airflow.env down -v" >&2
    return
  fi
  docker compose -p ew-smoke -f deploy/compose.yaml --env-file "$home/airflow.env" down -v >/dev/null 2>&1 || true
  if ! rm -rf "$home" 2>/dev/null; then
    docker run --rm --user 0 --entrypoint rm -v "$home:/cleanup" "$image" -rf /cleanup/logs >/dev/null 2>&1 || true
    rm -rf "$home" 2>/dev/null || echo "warning: could not remove $home" >&2
  fi
}
trap 'status=$?; cleanup; exit $status' EXIT
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

# The last top-level JSON array in a command's output. Airflow's CLI can print warnings before its
# data (the slim image warns that graphviz is missing), so its tables cannot be trusted to parse.
# An array that decodes is skipped over whole: arrays nested inside it ("roles": [...]) are part
# of it, never candidates themselves.
json_array() {
  python3 -c '
import json, sys
text, decoder, found, i = sys.stdin.read(), json.JSONDecoder(), [], 0
while i < len(text):
    if text[i] != "[":
        i += 1
        continue
    try:
        value, end = decoder.raw_decode(text, i)
    except ValueError:
        i += 1
        continue
    if isinstance(value, list):
        found = value
    i = end
print(json.dumps(found))'
}

echo "starting the production stack from $image ($([ "$throwaway" = 1 ] && echo throwaway || echo real) configuration) ..."
started=$SECONDS
if ! "${compose[@]}" up -d --wait --wait-timeout 300 >/dev/null; then
  echo "after $((SECONDS - started)) seconds:" >&2
  "${compose[@]}" ps -a --format '{{.Service}}: {{.Status}}' >&2
  # The evidence, before cleanup removes it: the logs of every service that exited or is unhealthy.
  for service in $("${compose[@]}" ps -a --format '{{.Service}} {{.Status}}' \
      | awk '/Exited \([1-9]|unhealthy|Restarting|starting/ {print $1}'); do
    echo "--- the last 40 lines of $service:" >&2
    "${compose[@]}" logs --no-color --tail 40 "$service" >&2 || true
  done
  echo "FAIL: the stack did not become healthy" >&2
  exit 1
fi
echo "healthy after $((SECONDS - started)) seconds"
"${compose[@]}" ps --format '{{.Service}}: {{.Status}}'

echo "--- the DAG folder, parsed inside the image as the DAG processor does:"
parsed="$("${compose[@]}" exec -T airflow-scheduler python - < scripts/parse_dags.py 2>/dev/null \
  | sed -n 's/^PARSE_RESULT //p' | tail -1 || true)"
if [ -z "$parsed" ]; then
  fail "the DAG folder could not be parsed"
else
  dags="$(echo "$parsed" | python3 -c 'import json, sys; print(" ".join(json.load(sys.stdin)["dags"]))')"
  errors="$(echo "$parsed" | python3 -c 'import json, sys; [print(f"  {f}: {e}") for f, e in json.load(sys.stdin)["errors"].items()]')"
  echo "DAGs: $dags"
  if [ -n "$errors" ]; then echo "$errors"; fail "a DAG file failed to import"; fi
  if [ "$dags" != "$expected_dags" ]; then fail "expected exactly: $expected_dags"; fi
fi

echo "--- the same DAGs, registered by the running DAG processor (it parses in the background):"
registered=""; raw=""
for attempt in $(seq 1 24); do
  raw="$("${compose[@]}" exec -T airflow-scheduler airflow dags list -o json 2>&1 || true)"
  registered="$(echo "$raw" | json_array \
    | python3 -c 'import json, sys; print(" ".join(sorted({d["dag_id"] for d in json.load(sys.stdin)})))' || true)"
  [ "$registered" = "$expected_dags" ] && break
  sleep 5
done
echo "registered: ${registered:-(none)} (attempt $attempt of 24)"
if [ "$registered" != "$expected_dags" ]; then
  echo "the last attempt's output:" >&2
  echo "$raw" | grep -vi openlineage | tail -8 >&2
  fail "the DAG processor did not register exactly the six DAGs within two minutes"
fi

echo "--- the admin user (created by airflow-init; without it, nobody can log in to the UI):"
# Retried: right after the stack reports healthy, the API server is still rewriting the FAB
# permission tables, and a read can fail while the user exists. The attempt count shows if so.
users=""; raw=""
for attempt in 1 2 3 4 5 6; do
  raw="$("${compose[@]}" exec -T airflow-scheduler airflow users list -o json 2>&1 || true)"
  users="$(echo "$raw" | json_array \
    | python3 -c 'import json, sys; print(" ".join(sorted(u["username"] for u in json.load(sys.stdin))))' || true)"
  [[ " $users " == *" admin "* ]] && break
  sleep 5
done
echo "users: ${users:-(none)} (attempt $attempt of 6)"
if [[ " $users " != *" admin "* ]]; then
  echo "the last attempt's output:" >&2
  echo "$raw" | grep -vi openlineage | tail -8 >&2
  fail "the admin user was not created"
fi

echo "--- every module the DAG code can import, top-level and inside functions:"
"${compose[@]}" exec -T airflow-scheduler python - < scripts/check_dag_imports.py \
  || fail "a module the DAG code imports is missing from the image"

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
