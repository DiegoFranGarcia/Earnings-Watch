# 15. Fix what can be fixed, accept the rest only with a reason and an expiry, and rescan what production runs

## Context

In November 2026 the deployed Airflow image had 972 known operating-system vulnerabilities, 139
of them with a fixed version available (63 critical or high), and its Python environments had
dozens more. Trivy only reported: nobody read 972 lines. The Postgres image had never been
scanned. A gate on all of it would block every build; no gate means nothing is ever looked at.

## Decision

**Triage by what runs, not by what is installed.** For each process (Airflow's Python, dbt's
Python, curl for the health checks, Postgres) we listed the Debian packages it actually loads,
from `/proc/self/maps` and `ldd`, and read every finding in those packages.

**Remove what nothing runs.** The Airflow image purges 15 packages: rsync, Perl apart from
perl-base (which Debian requires), git, libexpat1, the Postgres and MariaDB clients, SASL tools
and apt-utils. The purge downloads nothing, and the build fails if it would remove anything else.
The image went from 972 findings to 847; the fixable critical and high ones left are 15, in
perl-base, Brotli, OpenSSL's DTLS code, apt and pcre2, and all are accepted.

**Gate on what can be fixed.**

- Python (pip-audit): the lockfile and both of the image's environments; anything not accepted
  fails.
- Operating system (Trivy): both images; a fixable critical or high finding fails. Unfixed
  findings are not gated, since nothing can be done about them; those in loaded packages were
  read once, and none was reachable (SQLite's needs crafted SQL; zlib's is in minizip, which
  Debian does not ship in libz; Postgres's libxml2 serves an `xml` type the pipeline never uses).

**Accept only with a reason and an expiry.** `security/accepted-vulnerabilities.txt` (Python, by
ID and package) and `security/trivyignore.yaml` (OS, by ID and package) say why each finding
cannot be reached here, and until when: 90 days for unreachable code, or the date a fix should
have arrived, never more than 180. From that date the finding fails again.

**Rescan what production runs, every week.** On Mondays the deployed release and the pinned
Postgres are scanned again with the same rules, strictly: an acceptance expiring within 14 days,
or matching nothing any more, fails too, and GitHub emails the owner. Vulnerabilities published
after a release still surface: on 2026-11-17, 14 advisories against virtualenv appeared overnight.

## Consequences

- Every remaining finding has a reason and a review date; the next review is 2027-02-15.
- A new advisory fails CI on unrelated pull requests until it is fixed or accepted. That is
  deliberate: from then on, the fix is the most urgent change.
- **Blind spots no scanner here covers:** libraries bundled inside wheels and inside CPython.
  psycopg2-binary ships its own OpenSSL 1.1.1k (end of life since 2023), libpq, Kerberos, LDAP,
  SASL and pcre2; CPython's pyexpat carries its own expat (2.8.3, with CVE-2026-77214, fixed in
  Python 3.12.16). Their exposure is small: psycopg2 speaks only to Postgres on the containers'
  network, without TLS, and expat parses only AWS's replies, over TLS. The weekly scan compares
  CPython with python.org's releases, and accepts 3.12.14 until 2026-12-31. cryptography and
  awscrt bundle their own TLS too, but publish advisories under their own names, which pip-audit
  sees.

## Rejected

- **`apt-get upgrade` in the Dockerfile:** the same commit would build a different image each day.
- **Pinning individual apt versions:** Debian's archive drops superseded versions, and builds
  would break.
- **A custom minimal or distroless base:** we would own building Python and the Airflow image.
- **Gating unfixed findings:** it leads to permanent ignores, and then nobody reads the list. An
  upgrade from a fixed snapshot.debian.org date stays the escape hatch if a fix ever exists only
  there.
- **Scanning that only reports:** what we had: 972 lines, read by no one.

For the record: pull request #11 removed 15 virtualenv entries and 2 dnspython ones from the
accepted list; its commit message says 17 and 19.
