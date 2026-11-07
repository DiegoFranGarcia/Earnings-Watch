terraform {
  required_version = ">= 1.10.0"

  # Settings come from backend.hcl (not committed): terraform init -backend-config=backend.hcl
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "= 2.22.0" # pinned exactly: newer releases were under two weeks old
    }
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      project    = "earnings-watch"
      env        = "dev"
      managed_by = "terraform"
    }
  }
}
