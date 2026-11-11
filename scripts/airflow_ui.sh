#!/usr/bin/env bash
# Open the host's Airflow UI on http://localhost:8090, through an SSM port-forwarding session:
# AWS authenticates it, and the host has no open port. Needs AWS's Session Manager plugin
# (brew install --cask session-manager-plugin). Stop with Ctrl+C.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
instance="$(terraform -chdir=infra/envs/dev output -raw airflow_instance_id)"
echo "Airflow on the host: http://localhost:8090  (user: admin)"
echo "Password: aws secretsmanager get-secret-value --secret-id earningswatch/dev/airflow-internals --query SecretString --output text | python3 -c \"import json, sys; print(json.load(sys.stdin)['_AIRFLOW_WWW_USER_PASSWORD'])\""
exec aws ssm start-session --target "$instance" --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8090"]}'
