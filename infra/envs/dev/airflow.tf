variable "airflow_image" {
  description = "The host's first image (repository:commit); set in airflow.auto.tfvars."
  type        = string
}

variable "spark_code_uri" {
  description = "The host's first Spark code location; set in airflow.auto.tfvars."
  type        = string
}
