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

module "airflow_platform" {
  source              = "../../modules/airflow_platform"
  env                 = "dev"
  account_id          = data.aws_caller_identity.current.account_id
  lake_bucket_arn     = module.lake.bucket_arn
  emr_application_arn = module.spark.application_arn
  emr_job_role_arn    = module.spark.job_role_arn
}
