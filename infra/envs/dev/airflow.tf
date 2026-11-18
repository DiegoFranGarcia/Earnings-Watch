variable "airflow_image" {
  description = "The host's first image (repository:commit); set in airflow.auto.tfvars."
  type        = string
}

variable "spark_code_uri" {
  description = "The host's first Spark code location; set in airflow.auto.tfvars."
  type        = string
}

variable "alert_email" {
  description = "Where alarms are emailed; set in private.auto.tfvars, which git ignores. Required: without it, a plan would quietly delete the email alarm."
  type        = string

  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.alert_email))
    error_message = "alert_email must be an email address: set it in private.auto.tfvars."
  }
}
