variable "env" {
  description = "dev or prod."
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}

variable "account_id" {
  description = "AWS account ID, used to restrict who may assume the job role."
  type        = string
}

variable "lake_bucket_arn" {
  description = "ARN of the data lake bucket."
  type        = string
}

variable "release_label" {
  description = "EMR runtime. emr-spark-8.0.0 is Spark 4.0.2, matching local PySpark 4.0.2."
  type        = string
  default     = "emr-spark-8.0.0"
}

variable "max_vcpu" {
  description = "Hard ceiling on vCPUs running at once across all jobs: the cost cap."
  type        = number
  default     = 32
}

variable "max_memory_gb" {
  description = "Hard ceiling on memory running at once across all jobs, in GB."
  type        = number
  default     = 128
}

variable "max_disk_gb" {
  description = "Hard ceiling on worker disk across all jobs, in GB (20 GB per worker is free)."
  type        = number
  default     = 640
}
