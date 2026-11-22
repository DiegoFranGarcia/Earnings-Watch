# EarningsWatch runbook

How to operate the pipeline: what runs when, how to rerun or backfill safely, and what to do
when something breaks. Every step below is idempotent: rerunning it replaces exactly what it
covers and never duplicates data.

## How the pipeline runs

Each arrow is a data asset, not a clock: a DAG starts because new data arrived.

~~~text
SEC -> sec_daily_index (06:00 UTC daily) -> silver_daily_index -> snowflake_load_daily_index -> raw_daily_index -+
SEC -> sec_fsds_quarterly (quarterly) -> Spark on EMR -> silver_fsds -> snowflake_load -> raw_fsds --------------+-> dbt_build -> marts -> publish_site -> Site workflow -> GitHub Pages
SEC -> company_tickers_snapshot (07:00 UTC daily) -> bronze tickers
Airflow's records -> record_task_history (09:30 UTC daily) -> AUDIT.AIRFLOW_TASK_ATTEMPTS
~~~

- Failures alert the Discord channel after the task's last retry, with a link to its log.
- sec_daily_index must finish by 09:00 UTC, or a deadline alert fires (nothing may have failed:
  look for a run that is stuck or never started).
- Every morning sec_daily_index also checks that each business day of the last four weeks has its
  index in bronze (`check_landed_days`), and fails while one does not: see *A day of the daily
  index is missing*.

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

## A day of the daily index is missing

The alert: `sec_daily_index › check_landed_days failed`, "1 business day has no daily index in
bronze: 2026-11-05 (Thu)". That day's own run failed for good, or never ran, and the runs since
each fetch only their own day, so the gap stays until it is repaired. The alert repeats every
morning while the day is within the last four weeks; older gaps show only in
`scripts/reconcile_bronze.py`. Today's data is not held back.

1. **Did EDGAR publish it?** Open the quarter's folder in a browser, for example
   https://www.sec.gov/Archives/edgar/daily-index/2026/QTR4/, and look for `master.20261105.idx`.
2. **It is there:** land it with a run whose logical date is the next day at 06:00 UTC (a run
   fetches the day before its logical date). The landing announces the day; the month's reload,
   `dbt_build` and the site follow by themselves. Wait for it as in *Run a DAG on the host and
   wait for it*. Its deadline (three hours after the logical date) has long passed, so a deadline
   alert also arrives: expected.

   ~~~bash
   af='docker compose -p earningswatch -f /opt/earningswatch/deploy/compose.yaml --env-file /run/earningswatch/airflow.env exec -T airflow-scheduler airflow'
   scripts/host_exec.sh "$af dags trigger sec_daily_index -r manual__repair-2026-11-05 --logical-date 2026-11-06T06:00:00+00:00"
   ~~~

3. **It is not there:** EDGAR was closed that day. Add it to `CLOSURES` in
   `scripts/make_sec_closed_days.py` with the SEC's announcement as its source, run
   `uv run python scripts/make_sec_closed_days.py`, and merge: filing deadlines on that day move,
   and the check stops reporting it.

Found and repaired this way on 2026-11-21 ([the incident](incidents/2026-11-05.md)).

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

Drilled on 2026-11-21: the gate failed, and the marts and the live site kept their last good
data ([chaos drills](chaos.md)).

## Reprocess an FSDS quarter from the SEC

Rerun `sec_fsds_quarterly` for the quarter's logical date. If the SEC republished the file, the
new version lands beside the old one under `version=...`, Spark converts that exact folder, and
the load and dbt follow.

## dbt

- **After changing the dbt project, rebuild the manifest** that the Airflow DAG reads:
  `cd dbt && uv run dbt parse`. Otherwise Airflow keeps building from the old one.
- **A seed's columns changed:** `uv run dbt seed --full-refresh -s <seed>` once.
- **The days EDGAR was closed** (`sec_closed_days`, which moves filing deadlines) run to the end of
  `LAST_YEAR` in `scripts/make_sec_closed_days.py`. When `warn_sec_closed_days_run_out` warns
  (180 days before), raise `LAST_YEAR`, add any closure the SEC announced to `CLOSURES` with its
  source, and run `uv run python scripts/make_sec_closed_days.py`. Do the same mid-year if the
  government closes on a day it did not plan to (a national day of mourning): the SEC posts each
  one on its "What's New" page.
- **An incremental model's columns changed** (`on_schema_change='fail'` stops it on purpose):
  `uv run dbt build --full-refresh -s <model>` once.
- **Run one model and its tests:** `uv run dbt build -s <model>`.
- **A test failed:** read the rows, never just raise the threshold. Problems in filer data warn;
  problems in our logic fail (ADR 8).
- **How `dbt_build` orders tests:** each model's tests run right after it (`build.<model>.test`),
  except a test that reads several models, such as a relationship test, which is its own task
  (`build.<test>_test`) after all of them, as in `dbt build`. Such a test does not hold back the
  models built from its parents, but `publish` waits for every test, so a failure still keeps
  the site on its last good export. `tests/dags/test_dbt_build_order.py` holds both.
- **The site's screener window** (`site_recent_months`) counts back from the newest
  `known_at` in `mart_earnings_quality`, not from today: the screener only changes when new
  SEC data arrives.
- **To publish the same day after a failed build:** once the cause is fixed, rebuild what the
  failure held back with `uv run dbt build -s <models>` from your Mac (the host's database, ADR
  18), then *Publish by hand* (under "The public site").

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

## Run a DAG on the host and wait for it

From the Mac, in the repository. Triggering returns at once; to wait, ask for the run's state in a
loop. `dags state` prints the state first, then the run's conf if it has one
(`success, {"months": "2026-11"}`), so match the start of the line, not the whole line. (On the
host, `dags list-runs -o plain` printed nothing; ask for a named run instead.)

~~~bash
af='docker compose -p earningswatch -f /opt/earningswatch/deploy/compose.yaml --env-file /run/earningswatch/airflow.env exec -T airflow-scheduler airflow'
dag=snowflake_load_daily_index
run="manual__reload-$(date -u +%Y%m%dT%H%M%SZ)"
scripts/host_exec.sh "$af dags trigger $dag -r $run -c '{\"months\": \"2026-11\"}'"
while :; do
  s="$(scripts/host_exec.sh "$af dags state $dag $run" 2>/dev/null | grep -oE '^(queued|running|success|failed)\b' | tail -1)"
  echo "$(date -u +%H:%M:%S) $dag: ${s:-no answer yet}"
  { [ "$s" = success ] || [ "$s" = failed ]; } && break
  sleep 30
done
scripts/host_exec.sh "$af tasks states-for-dag-run $dag $run -o plain"
~~~

Name drill runs `manual__drill-<what>-<date>`, so they can be told apart from real runs.

## Merging a pull request

`main` takes changes only through pull requests whose six required checks passed on the branch
as it is, up to date with main: `lint-and-test`, `image-tests`, `security`, `dbt-slim-ci`,
`terraform` and `site` (`.github/rulesets/main.json`). Squash is the only merge allowed. GitHub
enforces this, so either way of merging is safe:

- **The button,** once every check is green; then `git switch main && git pull --ff-only`.
- **`scripts/merge_when_green.sh`**, from the pull request's branch, after pushing: it waits for
  the CI workflow on the exact commit you pushed and squash-merges only if it passed, so you need
  not watch. It does not wait for Site CI (the `site` check): if that is still running, GitHub
  refuses the merge; wait for it and run the script again.
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

## Task history

`record_task_history` copies every try of every task from Airflow's own records into
`AUDIT.AIRFLOW_TASK_ATTEMPTS` at 09:30 UTC, three days back, merging on DAG, run, task, map
index and try (reading a day twice changes nothing). A task a retry recovered keeps both tries.
It reads them through Airflow's REST API as `task-history`, a user with the read-only Viewer role:
the password is `TASK_HISTORY_PASSWORD` in the `airflow-internals` secret, set on the user by
`airflow-init` at every start, and the task asks for a fresh token each run.

- **Set up once, before the release that adds it reaches the host:**
  `uv run python scripts/create_airflow_internals_secret.py` (adds only the missing key) and
  `uv run python scripts/create_audit_tables.py`. Without the key the host still starts; only this
  DAG fails, and says why.
- **Rotate the password** each February, the same week as the dispatch token:
  `uv run python scripts/create_airflow_internals_secret.py --rotate TASK_HISTORY_PASSWORD`. The
  host applies it at its next start.
- **It failed with HTTP 401:** the user's password and the secret disagree, which the next start
  fixes; or `airflow-init` could not set the user up (its log says why).
- What the credentials can reach: read-only run history, as the smoke test checks (listing runs
  works, starting a DAG is refused). Tasks run inside the scheduler's container, which also holds
  Airflow's own secrets, so this limits what the recorder's code and any leaked token can do, not
  what a compromised scheduler could.

## The public site

**What runs.** After every `dbt_build` that passes, `publish_site` exports the dbt docs and the
site's seven tables (Parquet) to `exports/site/runs/<run>/` and points
`exports/site/current.json` at them, then starts the `Site` workflow (`.github/workflows/site.yml`).
Its four jobs: `export` (role `gha-site`) checks every file against the export's manifest;
`app`, with no credentials, builds the site's app (`site/`) from that export and puts it beside
the export's files; `deploy` publishes to GitHub Pages:
<https://diegofrangarcia.github.io/Earnings-Watch/>; `verify`, with no credentials, then asks
the live site for what the SQL page downloads, as a browser does, and checks it against what was
deployed (`scripts/verify_live_site.py`; its step summary lists every file and the bytes Pages
sent). It also runs daily at 10:30 UTC, and when `site.yml`, `scripts/build_site.py`,
`scripts/verify_live_site.py` or anything in `site/` changes on main. See ADR 17, 19 and 20.

**Check it.** Every page's status line shows the latest quarter in the data and when the export
ran; `site.json` says which export is live:

~~~bash
curl -s https://diegofrangarcia.github.io/Earnings-Watch/site.json
gh run list --workflow Site --limit 5
~~~

**Redeploy the latest export, or roll back to an older one:**

~~~bash
gh workflow run site.yml                                              # the latest
aws s3 ls "s3://$LAKE_BUCKET/exports/site/runs/"                       # the exports there are
gh workflow run site.yml -f export=exports/site/runs/<run>            # roll back to that one
~~~

A rollback lasts until the next export or the next scheduled run deploys the latest again. Only
exports that hold all seven tables can be deployed: none from before 2026-11-19.

**Publish by hand** (the same code the DAG runs; your AWS session and dbt profile):

~~~bash
PYTHONPATH=airflow/dags uv run python -m earningswatch.site_export --bucket "$LAKE_BUCKET" --dispatch
~~~

**If `trigger_site_deploy` failed:** the export is already published, and the 10:30 UTC run
deploys it. The usual cause is the token: `GitHub answered 401` means it expired or was
revoked; rotate it (below). `403` means it lacks Actions: write on this repository.

**If the Site workflow failed:** its log says why, and the live site is unchanged.
`NOT DEPLOYED: ...` in `export` means the export did not match its manifest, lacked a table, or
listed a file the site's layout does not know; in `app`, that the app's build would have replaced
one of the export's files. A failed `npm run build` usually means the export and the app disagree
about a table: the `site` check on pull requests builds the same app against a fixture with the
contract's shape. A file over the 20 MB budget stops the export itself, in `publish_site`.

**If `verify` failed:** the site is already live, and it does not serve what was deployed. Read
the job's summary before changing anything:
- *site.json still says '<an earlier run>', not the deployed '<this run>'*: Pages kept serving
  the previous `site.json` for over 12 minutes. Check by hand (`curl -s .../site.json`); if it
  has changed since, rerun the job (`gh run rerun <run-id> --failed`).
- *a file with another sha256, or HTTP 404*: Pages serves something other than the deploy. Rerun
  the job once; if it fails again, redeploy (`gh workflow run site.yml`) and find out why.
- *Pages now sends br (or zstd)*: Pages changed how it compresses. Browsers read it, this check
  cannot: extend `decoded()` in `scripts/verify_live_site.py`.
- *the SQL page says about N MB, but Pages sent M MB*: the estimate in
  `site/src/routes/sql/+page.server.js` no longer matches what Pages sends: find out what
  changed (a new DuckDB, Pages' compression) and correct the estimate.

**The SQL page says "the site's data was updated... Reload the page"**: a table it downloaded
did not match the live `site.json` (ADR 20), normally only in the minutes after a deploy. If it
lasts, compare `site.json` with `verify`'s summary of the last deploy.

**If the build stops at the DuckDB extension** (the SQL console, ADR 20):
`site/scripts/fetch-duckdb-extensions.mjs` downloads DuckDB's Parquet extension from
extensions.duckdb.org and checks it against `site/duckdb-extensions.json`. A size or sha256
mismatch means the file changed upstream: do not just update the hash; find out why first. "update
both together" means `@duckdb/duckdb-wasm` was upgraded (Dependabot) without the extensions: pin
the new DuckDB version's extension, its size and sha256, in the same pull request.

**If the scheduled runs stopped:** GitHub disables a public repository's schedules after 60
days without activity. `gh workflow enable site.yml` turns it back on.

### The dispatch token

A fine-grained personal access token, kept in Secrets Manager as
`earningswatch/dev/github-dispatch-token`, read by `trigger_site_deploy` when it runs.

- **Expires 2027-02-16** (90 days, the longest GitHub allows here). GitHub emails a reminder
  before then; rotate it a week ahead, the same week the Trivy suppressions come up (2027-02-15).
- To rotate: on GitHub, Settings → Developer settings → Personal access tokens → Fine-grained
  tokens → `earningswatch-site-dispatch` → Regenerate token (same scope: only
  `DiegoFranGarcia/Earnings-Watch`, Repository permissions → Actions: Read and write). Copy it,
  then store it without it reaching your screen or shell history (zsh):

  ~~~bash
  read -rs 'token?Paste the token, then press Enter: ' && echo
  printf '%s' "$token" | aws secretsmanager put-secret-value \
    --secret-id earningswatch/dev/github-dispatch-token --secret-string file:///dev/stdin \
    --query VersionId --output text
  unset token; pbcopy </dev/null    # clear the variable and the clipboard
  ~~~

  Then update the expiry date above, and test it with *Publish by hand*. The same week, rotate
  task-history's password (*Task history*, above).
