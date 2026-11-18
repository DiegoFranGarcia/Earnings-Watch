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

output "airflow_instance_id" {
  value = module.airflow_host.instance_id
}

output "github_plan_role_arn" {
  value = module.github_oidc.plan_role_arn
}

output "github_deploy_role_arn" {
  value = module.github_oidc.deploy_role_arn
}

output "github_scan_role_arn" {
  value = module.github_oidc.scan_role_arn
}

output "github_site_role_arn" {
  value = module.github_oidc.site_role_arn
}
