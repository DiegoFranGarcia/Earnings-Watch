#!/usr/bin/env bash
# Deploy the current release to the Airflow host, if it is running. A stopped host starts the
# current release at its next start (05:45 UTC), so that is not a failure. Fails if the host ends
# up running anything other than the current release (for example, after rolling back).
#
#   scripts/deploy_release.sh        (HOST_NAME_TAG defaults to earnings-watch-dev-airflow)
set -euo pipefail

tag="${HOST_NAME_TAG:-earnings-watch-dev-airflow}"
read -r instance state < <(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=$tag" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[0].Instances[0].[InstanceId, State.Name]' --output text)
if [ -z "$instance" ] || [ "$instance" = "None" ]; then
  echo "no instance tagged $tag" >&2
  exit 1
fi
if [ "$state" != "running" ]; then
  echo "host $instance is $state: it starts the current release at its next start"
  exit 0
fi

command_id=""
for _ in $(seq 1 12); do  # a just-started host's SSM agent can take a minute to register
  command_id="$(aws ssm send-command --instance-ids "$instance" --document-name AWS-RunShellScript \
    --parameters '{"commands":["earningswatch-deploy"],"executionTimeout":["1800"]}' \
    --query Command.CommandId --output text 2>/dev/null)" && break
  sleep 10
done
[ -n "$command_id" ] || { echo "could not reach $instance through SSM" >&2; exit 1; }

for _ in $(seq 1 180); do  # up to 30 minutes
  status="$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
    --query Status --output text 2>/dev/null || echo Pending)"
  case "$status" in Pending | InProgress | Delayed) sleep 10 ;; *) break ;; esac
done
aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance" \
  --query '[StandardOutputContent, StandardErrorContent]' --output text | grep -v '^None$' || true
echo "--- $status on $instance"
[ "$status" = "Success" ]
