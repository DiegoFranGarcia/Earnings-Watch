variable "env" {
  description = "dev or prod."
  type        = string

  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be dev or prod."
  }
}

variable "account_id" {
  description = "AWS account ID; makes the bucket name globally unique."
  type        = string
}
