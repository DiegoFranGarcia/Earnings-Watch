# 13. CI reaches AWS through OIDC roles, one per context, and never holds a real secret

## Context

The repository is public. Its workflows build and push the image, publish releases, deploy to
the host, read the infrastructure for plans, and scan production. Long-lived AWS keys stored in
GitHub would grant all of that to anyone who could read them or change a workflow, and a public
repository invites pull requests from strangers.

## Decision

- GitHub Actions authenticates with short-lived OIDC tokens; no AWS key is stored in GitHub. Each
  role trusts one context, matched exactly on the token's subject, which names the account and
  the repository by their permanent numeric IDs: a repository re-created under the same name
  matches nothing.

  | Role | Trusted for | Can |
  |---|---|---|
  | `gha-plan` | pull requests | read only (AWS's ReadOnlyAccess, which cannot read secret values) |
  | `gha-deploy` | the `production` environment, which only main may use | push to the one ECR repository, write `artifacts/` in the lake, send commands by SSM to the host (matched by its Name tag) |
  | `gha-scan` | jobs on main | read `current.env`, pull from the ECR repository |

- CI never holds a real application secret. The smoke test starts the production image with
  generated, throwaway keys; the real ones live in Secrets Manager, read only by the host's role.
- dbt's slim CI is the one job with a credential: a Snowflake key for `SVC_CI`, whose role reads
  production and can create schemas only in `EARNINGSWATCH_CI`, on a warehouse with a 15-minute
  statement timeout. It runs only for pull requests from this repository, never for forks or
  Dependabot.
- Workflows default to `contents: read`, and each job asks for more only if it needs it.
  Third-party actions are pinned to commit SHAs; downloaded tools (Trivy, gitleaks, the AWS CLI)
  are checked against pinned checksums.
- `main` changes only through pull requests whose required checks passed, with no bypass
  (`.github/rulesets/main.json`).

## Consequences

- A leaked workflow log or a malicious pull request yields at most read-only access, for the
  length of one job.
- A new workflow that needs AWS needs a new role, with its own trust and permissions, in
  Terraform: reviewed like any other change.
- A fork's pull request gets lint, tests, the image tests and the scans, but no dbt build against
  Snowflake; that needs a branch in this repository.

## Rejected

- **Access keys in GitHub secrets:** long-lived, and readable by any workflow change that reaches
  them.
- **One role for everything:** a pull request would hold the power to deploy.
- **Trusting `repo:Owner/Name:*`:** any context, including a pull request, could assume the
  deploy role; and a name can be reused by someone else.
- **Real secrets in the smoke test:** the test needs a working stack, not real credentials.
