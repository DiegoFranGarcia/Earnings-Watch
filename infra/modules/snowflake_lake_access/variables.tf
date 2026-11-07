variable "env" {
  description = "dev or prod."
  type        = string
}

variable "account_id" {
  description = "AWS account that owns the lake."
  type        = string
}

variable "bucket_name" {
  description = "The data lake bucket."
  type        = string
}

variable "bucket_arn" {
  description = "ARN of the data lake bucket."
  type        = string
}

variable "database" {
  description = "Database holding the RAW schema the stage lives in."
  type        = string
}

variable "loader_role" {
  description = "Account role allowed to load from the stage."
  type        = string
}
