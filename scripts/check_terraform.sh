#!/usr/bin/env bash
# The Terraform code's static checks: formatting, validation, tflint, and Trivy's misconfiguration
# scan, gated by scripts/trivy_gate.py against security/trivyignore-terraform.yaml.
#
#   scripts/check_terraform.sh [--strict]
#
# No credentials: nothing here reads the state or calls AWS or Snowflake; plans stay on a machine
# that holds the keys (ADR 16). Terraform, tflint and Trivy are downloaded at pinned versions and
# checked against pinned checksums; Trivy uses the checks built into that version, so the rules
# change only when Trivy is upgraded. The tools' output goes to stderr (the log), the gate's
# Markdown summary to stdout. Linux x86_64 only: the CI runner.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
[ "$(uname -s)/$(uname -m)" = Linux/x86_64 ] || { echo "Linux x86_64 only (the CI runner)" >&2; exit 2; }
exec 3>&1 1>&2
tools="$(mktemp -d)"
trap 'rm -rf "$tools"' EXIT

fetch() { # fetch <url> <sha256> <file>
  curl -fsSL -o "$tools/$3" "$1"
  echo "$2  $tools/$3" | sha256sum -c --quiet -
}
fetch https://releases.hashicorp.com/terraform/1.16.6/terraform_1.16.6_linux_amd64.zip \
  38034b38d03096399a7a1264a14561a8029b2b496fd1f169452656e53968f1b7 terraform.zip
fetch https://github.com/terraform-linters/tflint/releases/download/v0.65.0/tflint_linux_amd64.zip \
  d4c545ed2e29d6338604b586f34f544f380f70f243aa72f7b484713835eaec61 tflint.zip
fetch https://github.com/aquasecurity/trivy/releases/download/v0.76.1/trivy_0.76.1_Linux-64bit.tar.gz \
  c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0 trivy.tgz
unzip -qo "$tools/terraform.zip" terraform -d "$tools"
unzip -qo "$tools/tflint.zip" tflint -d "$tools"
tar -xzf "$tools/trivy.tgz" -C "$tools" trivy
roots=(infra/envs/dev infra/bootstrap)

echo "--- terraform fmt"
"$tools/terraform" fmt -check -recursive -diff infra
for root in "${roots[@]}"; do
  echo "--- terraform validate: $root"
  "$tools/terraform" -chdir="$root" init -backend=false -input=false -lockfile=readonly >/dev/null
  "$tools/terraform" -chdir="$root" validate -no-color
done

echo "--- tflint (its AWS ruleset is downloaded and signature-checked by tflint itself)"
"$tools/tflint" --config "$PWD/infra/.tflint.hcl" --init
for root in "${roots[@]}"; do
  echo "--- tflint: $root"
  "$tools/tflint" --chdir "$root" --config "$PWD/infra/.tflint.hcl" --call-module-type=local --format compact
done

echo "--- Trivy: misconfigurations"
"$tools/trivy" config --quiet --skip-check-update --format json --output "$tools/raw.json" infra
"$tools/trivy" convert --quiet --format json --show-suppressed \
  --ignorefile security/trivyignore-terraform.yaml --output "$tools/gated.json" "$tools/raw.json"
python3 scripts/trivy_gate.py "$@" security/trivyignore-terraform.yaml "Terraform=$tools/gated.json" >&3
