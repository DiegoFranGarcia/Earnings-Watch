data "aws_caller_identity" "current" {}

module "lake" {
  source     = "../../modules/lake"
  env        = "dev"
  account_id = data.aws_caller_identity.current.account_id
}

module "spark" {
  source          = "../../modules/spark"
  env             = "dev"
  account_id      = data.aws_caller_identity.current.account_id
  lake_bucket_arn = module.lake.bucket_arn
}
