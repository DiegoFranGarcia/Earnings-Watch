#!/usr/bin/env bash
# Run shell commands on the Airflow host through SSM Run Command, and print their output. There is
# no SSH and no open port: the SSM agent on the host fetches the command from AWS.
#
#   scripts/host_exec.sh 'systemctl is-active earningswatch'
set -euo pipefail

commands="${1:?usage: scripts/host_exec.sh '<commands>'}"
cd "$(git rev-parse --show-toplevel)"
instance="$(terraform -chdir=infra/envs/dev output -raw airflow_instance_id)"
parameters="$(python3 -c 'import json, sys; print(json.dumps({"commands": [sys.argv[1]], "executionTimeout": ["1800"]}))' "$commands")"

command_id="$(aws ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript \
  --parameters "$parameters" --query Command.CommandId --output text)"

for _ in $(seq 1 360); do  # up to 30 minutes
  status="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
    --query Status --output text 2>/dev/null || echo Pending)"
  case "$status" in
    Pending | InProgress | Delayed) sleep 5 ;;
    *) break ;;
  esac
done

aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
  --query StandardOutputContent --output text
errors="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
  --query StandardErrorContent --output text)"
if [ -n "$errors" ] && [ "$errors" != "None" ]; then echo "--- stderr:" >&2; echo "$errors" >&2; fi
echo "--- $status" >&2
[ "$status" = "Success" ]
