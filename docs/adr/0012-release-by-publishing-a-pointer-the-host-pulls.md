# 12. Release by publishing a pointer, which the host pulls at start

## Context

Airflow runs on one EC2 host (t4g.large) that is awake only from 05:45 to 09:45 UTC: EventBridge
starts it for the morning's DAG runs and stops it afterwards. It has no inbound access at all and
is reached only through SSM. Most merges to main happen while it sleeps, so a deploy that pushes
to the host would usually find nothing to push to, and "which version is production running?"
would have no single answer.

## Decision

- A release is a small file, `artifacts/releases/current.env` in the lake bucket, naming the
  Airflow image (by the 12-character commit that last changed it) and the Spark code. CI's
  release job writes it on main, only after every check and a smoke test of that exact image
  (`scripts/publish_release.sh`).
- The host reads it at every start (`earningswatch-start`): it parses the file rather than
  executing it, pulls the image, starts the stack, and records the release as good once healthy.
  If a release fails to start, the host falls back to the last good one and alerts Discord.
- If the host is awake when a release is published, CI asks it through SSM to switch now
  (`scripts/deploy_release.sh`); a host already on that release does nothing.
- Images and Spark packages are named after the last commit that changed their own directories:
  a documentation change publishes a release that points to the same image, and nothing is
  rebuilt.
- Every night at 09:30 UTC the metadata database is dumped to S3. The host holds nothing that is
  not in code, the image, Secrets Manager or that backup.

## Consequences

- One file answers what production runs; rolling back is pointing it at an earlier release
  (`scripts/promote_release.sh`).
- A release merged in the evening runs at the next 05:45 UTC start, not at once. The morning
  check (ECR's last pull time, the night's backup) confirms it.
- A bad release costs at most one failed start: the host falls back and says so.
- The host can be destroyed and rebuilt from scratch: drilled in 19 minutes 42 seconds (runbook).

## Rejected

- **Pushing over SSH, or Ansible:** needs inbound access and a key to guard; the host has neither.
- **Deploying only by SSM push:** fails whenever the host sleeps, and records nothing about what
  should be running.
- **A `latest` tag:** not reproducible, and nothing to roll back to.
