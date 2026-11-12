variable "env" {
  description = "dev or prod."
  type        = string
}

variable "account_id" {
  type = string
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "lake_bucket_arn" {
  description = "The lake bucket; the host reads and writes bronze/, silver/ and airflow/ only."
  type        = string
}

variable "emr_application_arn" {
  description = "The one EMR Serverless application the host may run Spark jobs on."
  type        = string
}

variable "emr_job_role_arn" {
  description = "The one role the host may pass, and only to EMR Serverless."
  type        = string
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "alert_email" {
  description = "Where alarms are emailed. Empty: the topic exists, with no subscription."
  type        = string
  default     = ""
}
