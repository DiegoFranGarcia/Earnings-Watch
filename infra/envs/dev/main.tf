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
  alert_email         = var.alert_email
}

module "airflow_host" {
  source                = "../../modules/airflow_host"
  env                   = "dev"
  subnet_id             = module.airflow_platform.subnet_id
  security_group_id     = module.airflow_platform.security_group_id
  instance_profile_name = module.airflow_platform.instance_profile_name
  image                 = var.airflow_image
  spark_code_uri        = var.spark_code_uri
  lake_bucket           = module.lake.bucket_name
  emr_application_id    = module.spark.application_id
  emr_job_role_arn      = module.spark.job_role_arn
  snowflake_account     = "${var.snowflake_organization_name}-${var.snowflake_account_name}"
  snowflake_database    = "EARNINGSWATCH_DEV"
  alerts_topic_arn      = module.airflow_platform.alerts_topic_arn
}
