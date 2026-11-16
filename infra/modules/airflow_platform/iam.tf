# The Airflow host's identity: an instance role whose credentials AWS renews automatically, so no
# access key exists anywhere. It grants exactly what the pipeline does, and nothing more.

data "aws_iam_policy_document" "host_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "host" {
  name               = "earnings-watch-${var.env}-airflow-host"
  description        = "The Airflow host: lake prefixes, one EMR application, three secrets"
  assume_role_policy = data.aws_iam_policy_document.host_trust.json
}

# Session Manager (the UI tunnel) and Run Command (deploys), through the SSM agent.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.host.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "host" {
  statement {
    sid     = "LakePrefixesTheHostWrites"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${var.lake_bucket_arn}/bronze/*",
      "${var.lake_bucket_arn}/silver/*",
      "${var.lake_bucket_arn}/airflow/*", # task logs and metadata backups
    ]
  }

  statement {
    sid       = "ListTheLake"
    actions   = ["s3:ListBucket"]
    resources = [var.lake_bucket_arn]
  }

  statement {
    sid = "RunSparkOnOneApplication"
    actions = [
      "emr-serverless:GetApplication",
      "emr-serverless:StartApplication",
      "emr-serverless:StartJobRun",
      "emr-serverless:GetJobRun",
      "emr-serverless:CancelJobRun",
    ]
    resources = [var.emr_application_arn, "${var.emr_application_arn}/jobruns/*"]
  }

  statement {
    sid       = "PassTheJobRoleToEmrOnly"
    actions   = ["iam:PassRole"]
    resources = [var.emr_job_role_arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["emr-serverless.amazonaws.com"]
    }
  }

  statement {
    sid       = "ReadThisHostsSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for secret in aws_secretsmanager_secret.host : secret.arn]
  }

  # One object: the release CI publishes. The host cannot list releases or read their history.
  statement {
    sid       = "ReadTheCurrentRelease"
    actions   = ["s3:GetObject"]
    resources = ["${var.lake_bucket_arn}/artifacts/releases/current.env"]
  }

  statement {
    sid       = "LogInToEcr"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # AWS defines this action on no resource
  }

  statement {
    sid = "PullFromOneRepository"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.airflow.arn]
  }
}

resource "aws_iam_role_policy" "host" {
  name   = "pipeline"
  role   = aws_iam_role.host.id
  policy = data.aws_iam_policy_document.host.json
}

resource "aws_iam_instance_profile" "host" {
  name = "earnings-watch-${var.env}-airflow-host"
  role = aws_iam_role.host.name
}
