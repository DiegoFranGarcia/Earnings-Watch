# EarningsWatch runbook

How to operate the pipeline: what runs when, how to rerun or backfill safely, and what to do
when something breaks. Every step below is idempotent: rerunning it replaces exactly what it
covers and never duplicates data.

## How the pipeline runs

Each arrow is a data asset, not a clock: a DAG starts because new data arrived.

~~~text
SEC -> sec_daily_index (06:00 UTC daily) -> silver_daily_index -> snowflake_load_daily_index -> raw_daily_index -+
SEC -> sec_fsds_quarterly (quarterly) -> Spark on EMR -> silver_fsds -> snowflake_load -> raw_fsds --------------+-> dbt_build -> marts
SEC -> company_tickers_snapshot (07:00 UTC daily) -> bronze tickers
~~~

- Failures alert the Discord channel after the task's last retry, with a link to its log.
- sec_daily_index must finish by 12:00 UTC, or a deadline alert fires (nothing may have failed:
  look for a run that is stuck or never started).

## Running locally

~~~bash
cd airflow && docker compose up -d     # UI on http://localhost:8080
aws login --profile earnings-watch     # the containers share this session; it expires
~~~

**An expired `aws login` is the most common failure locally**: tasks that touch S3 or EMR fail or
retry. Run `aws login` again, then clear the failed tasks. On EC2 (Stage 7) an instance role
removes this problem.

## A fresh environment

Airflow writes two tables in `AUDIT` as `LOADER`; create them before the first run, so they exist
(and are readable by dbt) from the start. Idempotent:

~~~bash
uv run python scripts/create_audit_tables.py
~~~

## Rerun a failed task

Clear it in the UI (the task, then **Clear**), or:

~~~bash
docker compose exec airflow-scheduler airflow tasks clear <dag_id> -t '<task_regex>' -s <start> -e <end> -y
~~~

Every task writes one partition idempotently, so clearing and rerunning is always safe.

## Reload data into Snowflake

| What | How |
|---|---|
| One FSDS quarter | Trigger `snowflake_load` with `{"quarters": "2026q3"}` |
| Many quarters, or all | `{"quarters": "2009q2..2026q3"}` (about 25 minutes, one task per quarter) |
| One month of the daily index | Trigger `snowflake_load_daily_index` with `{"months": "2026-11"}` |

~~~bash
docker compose exec airflow-scheduler airflow dags trigger snowflake_load -c '{"quarters": "2026q3"}'
~~~

Each quarter or month is one transaction: delete, `COPY ... FORCE = TRUE`, count, and commit only
if the count matches (Spark's reconciliation record for FSDS, the files themselves for the daily
index). A mismatch fails immediately, with no retry, and rolls back: RAW is unchanged. Investigate
the source before rerunning. `dbt_build` follows automatically.

## A volume check failed

`dbt_build` starts with a volume gate. If the newest day of filings is under half its usual
volume, or the newest quarter under half (or over double) the same quarter a year earlier, the
build stops and **the marts keep their last good data**. Every result is in `AUDIT.DQ_RESULTS`.

1. Read the alert: it names the check, the day or quarter, and the ratio.
2. Investigate the source: is the SEC's file complete? Did the load load all of it?
3. If the data is wrong, fix the source and reload. If it is genuinely unusual (Christmas Eve
   really is quiet), trigger `dbt_build` by hand with `{"accept_volume": true}`.

~~~bash
docker compose exec airflow-scheduler airflow dags trigger dbt_build -c '{"accept_volume": true}'
~~~

## Reprocess an FSDS quarter from the SEC

Rerun `sec_fsds_quarterly` for the quarter's logical date. If the SEC republished the file, the
new version lands beside the old one under `version=...`, Spark converts that exact folder, and
the load and dbt follow.

## dbt

- **After changing the dbt project, rebuild the manifest** that the Airflow DAG reads:
  `cd dbt && uv run dbt parse`. Otherwise Airflow keeps building from the old one.
- **A seed's columns changed:** `uv run dbt seed --full-refresh -s <seed>` once.
- **An incremental model's columns changed** (`on_schema_change='fail'` stops it on purpose):
  `uv run dbt build --full-refresh -s <model>` once.
- **Run one model and its tests:** `uv run dbt build -s <model>`.
- **A test failed:** read the rows, never just raise the threshold. Problems in filer data warn;
  problems in our logic fail (ADR 8).

## Releases

A release is `artifacts/releases/current.env` in the lake bucket: the Airflow image and the Spark
code production runs ([ADR 12](adr/0012-release-by-publishing-a-pointer-the-host-pulls.md)).

1. A pull request merges into main. CI runs every check, then the release job builds a new image
   only if something under `airflow/`, `dbt/` or `deploy/` changed since the last one (the image
   is named after the last commit that touched them), smoke-tests it, and publishes `current.env`.
2. If the host is awake, CI switches it to the new release at once. If it sleeps, it starts the
   release at 05:45 UTC.

**What is production running, and did last night go well?** The image should have been pulled
just after 05:45 UTC, and `airflow/backups/` should hold that day's backup from 09:30 UTC:

~~~bash
export AWS_PROFILE=earnings-watch
lake="$(terraform -chdir=infra/envs/dev output -raw lake_bucket)"
release="$(aws s3 cp --only-show-errors "s3://$lake/artifacts/releases/current.env" - | sed -n 's/^AIRFLOW_IMAGE=.*://p')"
echo "current release: $release"
aws ecr describe-images --repository-name earnings-watch-dev/airflow --image-ids imageTag="$release" \
  --query 'imageDetails[0].lastRecordedPullTime' --output text
aws s3 ls "s3://$lake/airflow/backups/" | tail -2
~~~

**Deploy now:** `scripts/deploy_release.sh`, with no arguments. It switches a running host to the
current release; a stopped host is not a failure, as it starts the current release at 05:45 UTC.
It fails if the host ends up running anything other than the current release.

**Roll back:** point `current.env` at an earlier release, then deploy it if the host is awake:

~~~bash
LAKE_BUCKET="$lake" scripts/promote_release.sh            # lists the recent releases
LAKE_BUCKET="$lake" scripts/promote_release.sh <commit>   # makes that one current
scripts/deploy_release.sh                                 # if the host is awake
~~~

**The next merge into main publishes over a rollback.** Fix forward: revert or fix the change in
a pull request, so main and production agree again.

**A start fell back** (Discord says so): the host is running its last good release. Find out why
the new one failed before anything else:

~~~bash
scripts/host_exec.sh 'journalctl -u earningswatch --since today --no-pager | tail -60'
~~~

## Merging a pull request

`main` takes changes only through pull requests whose required checks passed: `lint-and-test`,
`image-tests`, `security`, `dbt-slim-ci` and `terraform` (`.github/rulesets/main.json`).

- **Merge with `scripts/merge_when_green.sh`**, from the pull request's branch, after pushing.
  It waits for CI on the exact commit you pushed, watches it, and squash-merges only if it
  passed. Waiting on the branch instead is not enough: after a second push, the branch's newest
  run can still be the first push's.
- **"The head branch is not up to date":** `gh pr update-branch`, wait for the checks again, merge.
- **An emergency that cannot wait for the checks:** Settings, Rules, Rulesets, `main`: set
  Enforcement to Disabled, merge, say why in the pull request, then restore the ruleset exactly
  as in code with `scripts/apply_branch_ruleset.sh`.

## A security scan failed

Scans run on every pull request (CI's `image-tests` and `security` jobs) and every Monday at
11:23 UTC on what production runs (`scheduled-scan.yml`; a failure emails the owner). Open the
run's **Summary** first: it names each finding. Rules: [ADR 14](adr/0014-adopt-a-dependency-version-only-once-it-is-two-weeks-old.md)
and [ADR 15](adr/0015-fix-what-can-be-fixed-accept-the-rest-with-an-expiry.md).

| The run says | Do |
|---|---|
| `NOT ACCEPTED` (pip-audit) or **Blocking** (Trivy) | Fix it: a newer version at least 14 days old. Python: pin it in `airflow/constraint-overrides.txt`, with the reason, and check its requirements against Airflow's constraints (pin a dependency too if needed). Debian: a newer base image (Dependabot), or remove the package if nothing runs it. If there is no such fix and the code cannot be reached here, accept it instead: `security/accepted-vulnerabilities.txt` or `security/trivyignore.yaml`, with the reason and an expiry date. |
| An acceptance **expires** within 14 days, or has expired | Look again: if a fix now exists, pin it and remove the entry; if not, write the current reason and a new date (at most 180 days away). |
| An entry **matches nothing any more** | The finding is gone: remove the entry. |
| `pip-audit produced no report` | PyPI did not answer, even after a retry. Rerun the failed jobs: `gh run rerun <run id> --failed`. |
| The image's Python is **behind** | A newer base image (a Dependabot digest, or an Airflow upgrade), or a new date and reason in `security/python-freshness.txt`. |
| CI's `terraform` job: a **failed check** (Trivy) or a tflint finding | Fix the Terraform. If the setting is by design, accept the check in `security/trivyignore-terraform.yaml`, scoped to its file by path, with the reason and an expiry date ([ADR 16](adr/0016-check-terraform-statically-in-ci-and-plan-locally.md)). |

Run the scheduled scan by hand at any time: `gh workflow run scheduled-scan.yml`. **GitHub pauses
schedules after 60 days without activity in the repository:** the Actions tab then shows a banner.
`gh workflow enable scheduled-scan.yml` restarts it.

## Dependabot pull requests

Dependabot proposes rebuilds of the same version of the Airflow and Postgres base images (a new
digest, at least 14 days old). Check that only the digest changed, not the version, and that
every check passed, including both scans; then merge. If the rebuild fixed an accepted finding,
Trivy warns that its entry matches nothing: remove it in a follow-up pull request, before the
Monday scan, which fails on that warning.

## Rebuild the host from scratch

The host holds nothing that is not in code, the image, Secrets Manager or the nightly backup. To
replace it (lost, corrupted, or to pick up a new AMI or bootstrap):

~~~bash
terraform -chdir=infra/envs/dev plan -destroy -target=module.airflow_host -out=destroy.tfplan
terraform -chdir=infra/envs/dev apply destroy.tfplan      # check: 7 to destroy, nothing else
terraform -chdir=infra/envs/dev plan -out=dev.tfplan       # check: 7 to add
terraform -chdir=infra/envs/dev apply dev.tfplan
# wait until: scripts/host_exec.sh 'systemctl is-active earningswatch' prints active
scripts/host_exec.sh 'earningswatch-restore'              # or: earningswatch-restore airflow-<date>.sql.gz
~~~

Check each step's result before the next. Drilled on 2026-11-13: **19 minutes 42 seconds** from
destroy to a healthy Airflow with that morning's runs restored. `airflow.auto.tfvars` names the
image a new host starts with; point it at the current release first.

## Rotate a Snowflake service user's key

Snowflake holds two public keys per user, so a key can change with no downtime:

1. Generate a new pair in `~/.snowflake/keys/`: `openssl genrsa 2048 | openssl pkcs8 -topk8
   -inform PEM -out <user>_rsa_key_new.p8 -nocrypt`, then `openssl rsa -in ... -pubout`.
2. Set it as the user's second key (`rsa_public_key_2` in Terraform), and apply.
3. Point the clients at the new private key (`airflow/.env`, the compose mount), restart them.
4. Move the new key into `rsa_public_key`, remove `rsa_public_key_2`, apply, and delete the old
   private key.

## Tests

| Command | What it checks |
|---|---|
| `uv run pytest -q` | Unit tests, Spark parity, and the dbt project's guards |
| `scripts/test_dags.sh <image>` | Every DAG imports without network access; retries, timeouts, alerts and owners on every task (runs inside the Airflow image) |
| `cd dbt && uv run dbt build` | Every model, its contract and its tests, in Snowflake |

## Costs

Every Snowflake statement carries a query tag naming the pipeline step and the Airflow run:
`earningswatch:load:<run_id>` or `earningswatch:dbt:<run_id>`. `ACCOUNT_USAGE.QUERY_HISTORY`
and `QUERY_ATTRIBUTION_HISTORY` group credits by them.
