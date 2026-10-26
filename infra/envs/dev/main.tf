data "aws_caller_identity" "current" {}

module "lake" {
  source     = "../../modules/lake"
  env        = "dev"
  account_id = data.aws_caller_identity.current.account_id
}
