output "lake_bucket" {
  value = module.lake.bucket_name
}

output "emr_application_id" {
  value = module.spark.application_id
}

output "emr_job_role_arn" {
  value = module.spark.job_role_arn
}

output "ecr_repository_url" {
  value = module.airflow_platform.ecr_repository_url
}

output "airflow_secret_names" {
  value = module.airflow_platform.secret_names
}
