# Snowflake, managed as the TERRAFORM service user (created by infra/snowflake/bootstrap.sql).
# One Snowflake account serves every environment; it is managed from here until prod exists.

variable "snowflake_organization_name" {
  description = "First half of the account identifier (ORG-ACCOUNT)."
  type        = string
  default     = "TOHCGIQ"
}

variable "snowflake_account_name" {
  description = "Second half of the account identifier (ORG-ACCOUNT)."
  type        = string
  default     = "QM22072"
}

variable "snowflake_private_key_path" {
  description = "The TERRAFORM user's private key. Never in the repository."
  type        = string
  default     = "~/.snowflake/keys/terraform_rsa_key.p8"
}

provider "snowflake" {
  organization_name = var.snowflake_organization_name
  account_name      = var.snowflake_account_name
  user              = "TERRAFORM"
  role              = "TERRAFORM_ADMIN"
  authenticator     = "SNOWFLAKE_JWT"
  private_key       = file(pathexpand(var.snowflake_private_key_path))
}

module "snowflake" {
  source = "../../modules/snowflake"

  # One user per program, each with its own key pair in ~/.snowflake/keys/ (never in git).
  # SVC_AIRFLOW also holds REPORTER: publish_site reads MARTS read-only for the site's export.
  service_users = {
    SVC_AIRFLOW = { role = "LOADER", warehouse = "WH_LOAD", public_key_path = "~/.snowflake/keys/svc_airflow_rsa_key.pub", extra_roles = ["REPORTER"] }
    SVC_DBT     = { role = "TRANSFORMER", warehouse = "WH_TRANSFORM", public_key_path = "~/.snowflake/keys/svc_dbt_rsa_key.pub" }
    SVC_CI      = { role = "CI", warehouse = "WH_CI", public_key_path = "~/.snowflake/keys/svc_ci_rsa_key.pub" }
  }
}

module "snowflake_lake_access" {
  source = "../../modules/snowflake_lake_access"

  env         = "dev"
  account_id  = data.aws_caller_identity.current.account_id
  bucket_name = module.lake.bucket_name
  bucket_arn  = module.lake.bucket_arn
  database    = module.snowflake.schemas["EARNINGSWATCH_DEV.RAW"].database
  loader_role = module.snowflake.role_names["LOADER"]
}

output "snowflake_databases" {
  value = module.snowflake.databases
}

output "snowflake_warehouses" {
  value = module.snowflake.warehouses
}

output "snowflake_roles" {
  value = module.snowflake.roles
}

output "snowflake_service_users" {
  value = module.snowflake.service_users
}

output "snowflake_stage" {
  value = module.snowflake_lake_access.stage
}

output "snowflake_read_role_arn" {
  value = module.snowflake_lake_access.snowflake_read_role_arn
}
