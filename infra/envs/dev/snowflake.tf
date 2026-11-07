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
