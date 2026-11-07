# Snowflake reads the lake's silver/ folder through an IAM role: no AWS keys stored anywhere.
#
# The circular dependency, broken in one apply:
#   the integration must name the IAM role, but the role must trust an identity that
#   Snowflake only reveals once the integration exists. A role's ARN is predictable, so the
#   integration is created with the ARN as text first; the role is then created trusting
#   the identity and external ID the integration reports.

locals {
  role_name = "earnings-watch-${var.env}-snowflake-read"
  role_arn  = "arn:aws:iam::${var.account_id}:role/${local.role_name}"
  silver    = "s3://${var.bucket_name}/silver/"
}

resource "snowflake_storage_integration_aws" "lake" {
  name                      = "LAKE_${upper(var.env)}"
  enabled                   = true
  storage_provider          = "S3"
  storage_allowed_locations = [local.silver] # silver only: bronze and logs stay out of reach
  storage_aws_role_arn      = local.role_arn # built as text: the role does not exist yet
  comment                   = "Read access to the lake's silver/ folder"
}

locals {
  snowflake_identity = snowflake_storage_integration_aws.lake.describe_output[0]
}

data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "SnowflakeIntegrationOnly"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [local.snowflake_identity.iam_user_arn]
    }

    # The external ID ties the trust to this one integration, not to any Snowflake customer.
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [local.snowflake_identity.external_id]
    }
  }
}

resource "aws_iam_role" "snowflake" {
  name               = local.role_name
  description        = "Assumed by Snowflake's storage integration to read silver/."
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

data "aws_iam_policy_document" "read_silver" {
  statement {
    sid       = "ReadSilverObjects"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${var.bucket_arn}/silver/*"]
  }

  statement {
    sid       = "ListSilverOnly"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["silver/*"]
    }
  }
}

resource "aws_iam_role_policy" "read_silver" {
  name   = "read-silver"
  role   = aws_iam_role.snowflake.id
  policy = data.aws_iam_policy_document.read_silver.json
}

# -- what COPY INTO loads from ---------------------------------------------------------

resource "snowflake_file_format_parquet" "silver" {
  database               = var.database
  schema                 = "RAW"
  name                   = "SILVER_PARQUET"
  compression            = "AUTO"
  use_logical_type       = "true" # dates, timestamps and decimals load as real types
  use_vectorized_scanner = "true" # Snowflake's faster Parquet reader
  comment                = "Silver Parquet written by Spark (ZSTD inside Parquet)"
}

resource "snowflake_stage_external_s3" "silver" {
  database            = var.database
  schema              = "RAW"
  name                = "SILVER"
  url                 = local.silver
  storage_integration = snowflake_storage_integration_aws.lake.name
  comment             = "The lake's silver/ folder"

  file_format {
    format_name = snowflake_file_format_parquet.silver.fully_qualified_name
  }

  depends_on = [aws_iam_role_policy.read_silver] # usable only once the role can read
}

resource "snowflake_grant_privileges_to_account_role" "loader_stage" {
  account_role_name = var.loader_role
  privileges        = ["USAGE"]
  on_schema_object {
    object_type = "STAGE"
    object_name = snowflake_stage_external_s3.silver.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "loader_file_format" {
  account_role_name = var.loader_role
  privileges        = ["USAGE"]
  on_schema_object {
    object_type = "FILE FORMAT"
    object_name = snowflake_file_format_parquet.silver.fully_qualified_name
  }
}
