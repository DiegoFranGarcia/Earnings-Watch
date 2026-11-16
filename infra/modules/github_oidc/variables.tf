variable "env" {
  type = string
}

variable "account_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "repository" {
  description = "owner/name of the only GitHub repository these roles trust, matched exactly."
  type        = string
}

variable "lake_bucket_arn" {
  type = string
}

variable "ecr_repository_arn" {
  type = string
}

variable "host_name_tag" {
  description = "Name tag of the Airflow host, the only instance deploys may send commands to."
  type        = string
}
