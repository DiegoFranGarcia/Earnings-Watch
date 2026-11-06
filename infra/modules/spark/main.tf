# Spark on EMR Serverless: it scales to zero and bills per second only while a job runs.
#
# Cost guardrails, all deliberate:
# - no initial_capacity block: nothing is pre-warmed, so nothing bills while idle;
# - auto-stop after 15 idle minutes;
# - maximum_capacity caps what all jobs together can use at once (the worst-case hourly bill);
# - at most 2 jobs run at once (scheduler_configuration);
# - ARM64 (Graviton) workers, about 20% cheaper than x86 for this pure-Python job;
# - no network_configuration: no VPC, so no NAT gateway or public IPv4 charges.

resource "aws_emrserverless_application" "spark" {
  name          = "earnings-watch-${var.env}-spark"
  release_label = var.release_label
  type          = "SPARK" # emr-spark-8.0.0's documentation uses SPARK in upper case
  architecture  = "ARM64"

  maximum_capacity {
    cpu    = "${var.max_vcpu} vCPU"
    memory = "${var.max_memory_gb} GB"
    disk   = "${var.max_disk_gb} GB" # AWS's default ceiling is 400,000 GB
  }

  auto_start_configuration {
    enabled = true
  }

  auto_stop_configuration {
    enabled              = true
    idle_timeout_minutes = 15
  }

  # AWS attaches a scheduler with defaults (15 concurrent runs, 6-hour queue) to every new
  # application. Declaring it lets Terraform own it instead of trying to remove it on every
  # plan, and a low limit on concurrent runs is one more cost cap.
  scheduler_configuration {
    max_concurrent_runs   = 2
    queue_timeout_minutes = 360
  }
}

# -- the role the Spark jobs run as ------------------------------------------------

data "aws_iam_policy_document" "job_trust" {
  statement {
    sid     = "EmrServerlessJobsOfThisApplicationOnly"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["emr-serverless.amazonaws.com"]
    }

    # Guard against the confused-deputy problem: only this account's application may use it.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_emrserverless_application.spark.arn]
    }
  }
}

resource "aws_iam_role" "job" {
  name               = "earnings-watch-${var.env}-spark-job"
  description        = "Runs EarningsWatch Spark jobs: reads bronze FSDS, writes silver and logs."
  assume_role_policy = data.aws_iam_policy_document.job_trust.json
}

locals {
  lake = var.lake_bucket_arn
}

data "aws_iam_policy_document" "job_access" {
  statement {
    sid       = "ListOnlyTheLakePrefixesTheJobUses"
    actions   = ["s3:ListBucket"]
    resources = [local.lake]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "bronze/source=fsds/*",
        "silver*",
        "artifacts/spark/*",
        "logs/emr-serverless/*",
      ]
    }
  }

  statement {
    sid     = "ReadBronzeFsdsAndTheJobCode"
    actions = ["s3:GetObject"]
    resources = [
      "${local.lake}/bronze/source=fsds/*",
      "${local.lake}/artifacts/spark/*",
    ]
  }

  statement {
    sid = "WriteSilver"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject", # Spark replaces a quarter's partition and cleans up its temporary files
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${local.lake}/silver/*"]
  }

  statement {
    sid       = "WriteSparkLogs"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${local.lake}/logs/emr-serverless/*"]
  }
}

resource "aws_iam_role_policy" "job_access" {
  name   = "lake-access"
  role   = aws_iam_role.job.id
  policy = data.aws_iam_policy_document.job_access.json
}
