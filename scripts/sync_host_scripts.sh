#!/usr/bin/env bash
# Install the host's scripts on the running host, rendered from the bootstrap template, so the host
# and the repository never drift. The bootstrap installs them on a new host; this updates an
# existing one. Also adds any settings the scripts need that an older host lacks.
#
#   scripts/sync_host_scripts.sh
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

lake_bucket="$(terraform -chdir=infra/envs/dev output -raw lake_bucket)"
ecr_repository="$(terraform -chdir=infra/envs/dev output -raw ecr_repository_url)"

commands="$(python3 - "$lake_bucket" "$ecr_repository" <<'PY'
import re, sys
lake_bucket, ecr_repository = sys.argv[1:]
src = open("infra/modules/airflow_host/bootstrap.sh.tftpl").read()
out = []
for marker, path in (
    ("START", "/usr/local/bin/earningswatch-start"),
    ("DEPLOY", "/usr/local/bin/earningswatch-deploy"),
    ("BACKUP", "/usr/local/bin/earningswatch-backup"),
    ("RESTORE", "/usr/local/bin/earningswatch-restore"),
):
    body = src.split(f"<<'{marker}'\n", 1)[1].split(f"\n{marker}\n", 1)[0]
    body = body.replace("${env}", "dev")
    leftover = re.findall(r"\$\{[a-z_0-9]+\}", body)
    assert not leftover, f"{marker}: unrendered template values {leftover}"
    out.append(f"cat > {path}.new <<'{marker}'\n{body}\n{marker}\nchmod 755 {path}.new\nmv {path}.new {path}")
for key, value in (
    ("RELEASE_URI", f"s3://{lake_bucket}/artifacts/releases/current.env"),
    ("ECR_REPOSITORY", ecr_repository),
):
    out.append(f"grep -q '^{key}=' /opt/earningswatch/settings.env "
               f"|| echo '{key}={value}' >> /opt/earningswatch/settings.env")
out.append("grep -E '^(RELEASE_URI|ECR_REPOSITORY)=' /opt/earningswatch/settings.env")
out.append("ls -l /usr/local/bin/earningswatch-*")
print("\n".join(out))
PY
)"
scripts/host_exec.sh "$commands"
