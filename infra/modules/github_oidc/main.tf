# GitHub Actions authenticates to AWS with short-lived OIDC tokens: no AWS key is stored in GitHub.
# For each run, GitHub signs a token naming the repository and the context (a pull request, an
# environment); AWS checks the signature, then each role's conditions, which pin this repository
# exactly. Never use a wildcard in the repository: any GitHub repository could then assume the role.

# GitHub's subject claim names the account and repository with their permanent numeric IDs, e.g.
# repo:Owner@160972168/Name@1422352027:pull_request. A name can be freed and reused by someone else;
# an ID never is, so matching IDs means a different repository with the same name matches nothing.
locals {
  subject = format(
    "repo:%s@%s/%s@%s",
    split("/", var.repository)[0], var.repository_owner_id,
    split("/", var.repository)[1], var.repository_id,
  )
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust" {
  for_each = {
    plan   = "${local.subject}:pull_request"             # any pull request in this repository
    deploy = "${local.subject}:environment:production"   # only main may use this environment
    scan   = "${local.subject}:ref:refs/heads/main"      # any job on main: reviewed code only
    site   = "${local.subject}:environment:github-pages" # Pages deploys: only main may use it
  }

  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [each.value]
    }
  }
}

# Pull requests: read only. ReadOnlyAccess covers Terraform plans and the dbt manifest, and does
# not include secretsmanager:GetSecretValue, so a pull request can never read a secret's value.
resource "aws_iam_role" "plan" {
  name               = "earnings-watch-${var.env}-gha-plan"
  description        = "GitHub Actions, pull requests in ${var.repository}: read only"
  assume_role_policy = data.aws_iam_policy_document.trust["plan"].json
}

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# main, in the production environment: publish and deploy, nothing else.
resource "aws_iam_role" "deploy" {
  name               = "earnings-watch-${var.env}-gha-deploy"
  description        = "GitHub Actions, main in ${var.repository}: push the image, deploy by SSM"
  assume_role_policy = data.aws_iam_policy_document.trust["deploy"].json
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "LogInToEcr"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # AWS defines this action on no resource
  }

  statement {
    sid = "PushToOneRepository"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [var.ecr_repository_arn]
  }

  statement {
    sid       = "PublishArtifacts"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${var.lake_bucket_arn}/artifacts/*"] # Spark code and the dbt manifest
  }

  statement {
    sid       = "ListArtifacts"
    actions   = ["s3:ListBucket"]
    resources = [var.lake_bucket_arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["artifacts/*"]
    }
  }

  statement {
    sid       = "FindTheHost"
    actions   = ["ec2:DescribeInstances"]
    resources = ["*"] # describe actions have no resource-level permissions
  }

  # Run Command needs permission on both the document and the target instance. The host is
  # matched by its Name tag, not its ID, because a rebuild gives it a new ID.
  statement {
    sid       = "RunShellScripts"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${var.region}::document/AWS-RunShellScript"]
  }

  statement {
    sid       = "OnTheAirflowHostOnly"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ec2:${var.region}:${var.account_id}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/Name"
      values   = [var.host_name_tag]
    }
  }

  statement {
    sid       = "ReadCommandResults"
    actions   = ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"]
    resources = ["*"] # these actions have no resource-level permissions
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "publish-and-deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}

# The scheduled scan, on main: read which release is current, and pull its image. Nothing else:
# no secrets, no writes, no commands. GitHub issues a token for main only to workflows already
# on main, and they got there through a reviewed pull request.
resource "aws_iam_role" "scan" {
  name               = "earnings-watch-${var.env}-gha-scan"
  description        = "GitHub Actions, main in ${var.repository}: read the current release, pull its image"
  assume_role_policy = data.aws_iam_policy_document.trust["scan"].json
}

data "aws_iam_policy_document" "scan" {
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
    resources = [var.ecr_repository_arn]
  }

  statement {
    sid       = "ReadTheCurrentRelease"
    actions   = ["s3:GetObject"]
    resources = ["${var.lake_bucket_arn}/artifacts/releases/current.env"]
  }
}

resource "aws_iam_role_policy" "scan" {
  name   = "read-the-current-release"
  role   = aws_iam_role.scan.id
  policy = data.aws_iam_policy_document.scan.json
}

# The site workflow (.github/workflows/site.yml): read the published exports, nothing else. Trusted
# only for jobs in the github-pages environment, which GitHub lets only main deploy from.
resource "aws_iam_role" "site" {
  name               = "earnings-watch-${var.env}-gha-site"
  description        = "GitHub Actions, github-pages environment in ${var.repository}: read the site exports"
  assume_role_policy = data.aws_iam_policy_document.trust["site"].json
}

data "aws_iam_policy_document" "site" {
  statement {
    sid       = "ReadTheSiteExports"
    actions   = ["s3:GetObject"]
    resources = ["${var.lake_bucket_arn}/exports/site/*"]
  }
}

resource "aws_iam_role_policy" "site" {
  name   = "read-the-site-exports"
  role   = aws_iam_role.site.id
  policy = data.aws_iam_policy_document.site.json
}
