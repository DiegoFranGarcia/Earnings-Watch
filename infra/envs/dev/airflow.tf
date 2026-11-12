variable "airflow_image" {
  description = "The host's first image (repository:commit); set in airflow.auto.tfvars."
  type        = string
}

variable "spark_code_uri" {
  description = "The host's first Spark code location; set in airflow.auto.tfvars."
  type        = string
}

variable "alert_email" {
  description = "Where alarms are emailed; set in private.auto.tfvars, which git ignores."
  type        = string
  default     = ""
}
