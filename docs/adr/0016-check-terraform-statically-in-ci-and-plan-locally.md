# 16. Check Terraform statically in CI; plan only where the keys are

## Context

Pull requests that changed `infra/` had no automated check: their effect was seen only in a
`terraform plan` on a maintainer's machine. A plan in CI looked like the obvious fix, but the
`dev` root manages Snowflake as well as AWS, and refreshing it needs the `TERRAFORM` user's key,
whose role (`TERRAFORM_ADMIN`) creates users and grants roles. Any workflow in a pull request
could read that key; ADR 13 rules exactly that out.

`gha-plan`, which every pull request job from this repository can assume, can already read the
whole state. Checked on 2026-11-18, it holds no secret value: secrets are set outside Terraform,
and the only attributes marked sensitive are a public AMI parameter and the Snowflake service
users' `email` and `login_name`.

## Decision

- A required CI job, `terraform`, on every pull request and push (`scripts/check_terraform.sh`),
  with no credentials at all:
  - `terraform fmt -check`, and `validate` of both roots without a backend;
  - tflint 0.65.0 with the AWS ruleset 0.50.0: invalid instance types, deprecated arguments;
  - Trivy 0.76.1's misconfiguration scan, using the checks built into that version
    (`--skip-check-update`), so the rules change only when Trivy is upgraded (ADR 14).
- A failed CRITICAL or HIGH check fails the job, unless it is accepted in
  `security/trivyignore-terraform.yaml`: scoped to its file by path, with the reason and an
  expiry date, judged by the same `scripts/trivy_gate.py` as the images' findings (ADR 15).
- Plans stay local: whoever applies runs `plan` first, with the keys on their machine.
- `alert_email` is required: without it, a plan would quietly delete the email alarm.
- `airflow.auto.tfvars` is committed (an image and a code location, no secret);
  `private.auto.tfvars`, which holds the email address, stays out of the repository.

Accepted on 2026-11-18, all by design, until 2027-02-15:

| Check | Why |
|---|---|
| AWS-0104 unrestricted egress | The host's services sit behind CDNs; with no NAT gateway, egress by port is the tightest rule; no inbound rules |
| AWS-0164 public IP in the subnet | The same decision: a public address instead of a NAT gateway |
| AWS-0095 unencrypted SNS topic | CloudWatch alarms cannot publish to AWS's managed SNS key; the texts hold no secret |
| AWS-0132 S3 without a customer managed key | SSE-S3; a key policy for every reader, for no gain here |

## Consequences

- Every infrastructure change is checked for form and for known misconfigurations, not for what
  it will change in AWS: that remains the local plan's job, before every apply.
- CI holds no new credential, and the Snowflake admin key never leaves the maintainer's machine.
- Drift between the code and AWS is not detected automatically.

## Rejected

- **The `TERRAFORM` key as a CI secret:** a pull request's workflow could read Snowflake admin.
- **`terraform plan -target` for the AWS resources only:** targeting gives incomplete plans, and
  whether it needs the Snowflake provider depends on the dependency graph: too fragile for a
  required check.
- **Splitting Snowflake into its own root now:** the right end state, but surgery on production
  state with Stage 9 still ahead. When it is done: `removed` blocks (`destroy = false`) in the old
  root and `import` blocks in the new, so both plans show the move before anything is applied;
  the storage integration and its IAM role together in the Snowflake root, with a narrow AWS role
  for that one role; and `gha-plan` limited to the AWS root's state key.
