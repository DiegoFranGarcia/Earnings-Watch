terraform {
  required_version = ">= 1.10.0"

  # Settings come from backend.hcl (not committed): terraform init -backend-config=backend.hcl
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
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
