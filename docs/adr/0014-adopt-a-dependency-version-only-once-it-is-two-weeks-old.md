# 14. Adopt a dependency version only once it is two weeks old

## Context

Every image build installs a few hundred third-party packages, on top of base images, GitHub
Actions and scanning tools. A compromised or broken release of any of them runs with the
pipeline's access. Such releases are usually noticed and withdrawn within days: the risk is
concentrated in a version's first days.

## Decision

- **The rule:** a version may be adopted only once it has been published for at least 14 days.
- **Where a tool takes a date, it is set 15 days back.** `uv --exclude-newer` and similar options
  take a date, not a time; one day of margin keeps them past 14 days whatever the time zone. Pins
  made by hand are checked against the exact upload time.
- **Everything is pinned, so nothing changes by itself:**
  - Python: `uv.lock` for the project; `airflow/dbt-constraints.txt` (generated with
    `uv pip compile --exclude-newer`) for dbt; Airflow's own constraints for Airflow, with
    `airflow/constraint-overrides.txt` for the few versions we change.
  - Base images by digest; Dependabot proposes rebuilds of the same version, after a 14-day
    cooldown.
  - Actions by commit SHA; Trivy, gitleaks and pip-audit by version, and by checksum where
    downloaded.
- **Every override says why**, next to its pin; most fix a published vulnerability. When a fix
  needs another package newer than Airflow's pin (virtualenv 21.14.11 needs python-discovery
  1.6.1 or later), that package is pinned too, and the image build, smoke test and audits decide
  whether the set works.
- **A fix younger than 14 days waits,** and its vulnerability is accepted until then, with a
  reason and an expiry date (ADR 15). dnspython 2.9.2 was published on 2026-11-03 at 23:56 UTC
  and adopted on 2026-11-18. The one exception: a vulnerability that is both reachable here and
  actively exploited, and the pull request says so.

## Consequences

- A security fix usually reaches production about two weeks after it is published.
- Overrides accumulate. An Airflow upgrade brings new constraints, and each override is then
  removed or kept with its reason.
- Updates are deliberate: they arrive as pull requests through every check, never as a side
  effect of a rebuild.

## Rejected

- **Always the latest version:** a version's first days are its riskiest.
- **No pins:** the same commit would build differently on different days, and a failure could not
  be reproduced.
- **A longer wait (30 days):** fixes would wait twice as long, for little extra protection.
