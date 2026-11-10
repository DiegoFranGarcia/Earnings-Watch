# The image registry, and the host's secrets.

resource "aws_ecr_repository" "airflow" {
  name                 = "earnings-watch-${var.env}/airflow"
  image_tag_mutability = "IMMUTABLE" # an image tagged with a commit can never be overwritten

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Each image is about a gigabyte of storage; keep the five newest (enough to roll back).
resource "aws_ecr_lifecycle_policy" "airflow" {
  repository = aws_ecr_repository.airflow.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the five newest images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

# Secrets are created empty. Their values are set with the AWS CLI, never through Terraform:
# anything Terraform sets is stored in plain text in its state file.
resource "aws_secretsmanager_secret" "host" {
  for_each = {
    "svc-airflow-private-key" = "Snowflake private key of SVC_AIRFLOW (role LOADER)"
    "svc-dbt-private-key"     = "Snowflake private key of SVC_DBT (role TRANSFORMER)"
    "discord-webhook-url"     = "Discord webhook for pipeline alerts"
    "airflow-internals"       = "Airflow's database password, Fernet key, JWT secret, admin password; SEC_USER_AGENT"
  }

  name                    = "earningswatch/${var.env}/${each.key}"
  description             = each.value
  recovery_window_in_days = 7
}
