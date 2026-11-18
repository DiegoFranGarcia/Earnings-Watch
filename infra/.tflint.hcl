# tflint's configuration, for scripts/check_terraform.sh (CI) and local runs:
#   tflint --chdir infra/envs/dev --config "$PWD/infra/.tflint.hcl" --call-module-type=local
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

# Invalid instance types, deprecated arguments and similar AWS mistakes. Versions follow ADR 14.
plugin "aws" {
  enabled = true
  version = "0.50.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
