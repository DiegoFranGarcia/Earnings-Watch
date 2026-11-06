output "lake_bucket" {
  value = module.lake.bucket_name
}

output "emr_application_id" {
  value = module.spark.application_id
}

output "emr_job_role_arn" {
  value = module.spark.job_role_arn
}
