variable "env" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "security_group_id" {
  type = string
}

variable "instance_profile_name" {
  type = string
}

variable "image" {
  description = "The first image to run (repository:commit). Later images are deployed by SSM."
  type        = string
}

variable "spark_code_uri" {
  description = "The first Spark code location (s3://.../artifacts/spark/<commit>)."
  type        = string
}

variable "lake_bucket" {
  type = string
}

variable "emr_application_id" {
  type = string
}

variable "emr_job_role_arn" {
  type = string
}

variable "snowflake_account" {
  description = "ORGANIZATION-ACCOUNT"
  type        = string
}

variable "snowflake_database" {
  type = string
}

variable "instance_type" {
  type    = string
  default = "t4g.large" # Graviton: 2 vCPU, 8 GB
}

variable "root_volume_gb" {
  type    = number
  default = 30
}

variable "compose_version" {
  description = "Docker Compose plugin release; chosen when over two weeks old."
  type        = string
  default     = "v5.6.1"
}

variable "compose_sha256" {
  description = "SHA-256 of docker-compose-linux-aarch64 for compose_version, pinned here."
  type        = string
  default     = "42cfa75f51ad0ccf290bad37899e0038a8c10a0069e85233ecc1d53e3ff1347d"
}
