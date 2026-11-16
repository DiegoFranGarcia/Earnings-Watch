# The Airflow host: one Graviton instance running the production Compose stack.
#
# Deliberately separate from airflow_platform (network, role, registry, secrets), so it can be
# destroyed and rebuilt from code at any time. Its metadata database lives on its disk and is
# backed up to S3; everything else is in the image, the secrets and the settings below.

# The latest Amazon Linux 2023 for arm64, from AWS's public parameter.
data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "airflow" {
  ami                    = nonsensitive(data.aws_ssm_parameter.al2023_arm64.value)
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [var.security_group_id]
  iam_instance_profile   = var.instance_profile_name

  user_data = templatefile("${path.module}/bootstrap.sh.tftpl", {
    env                = var.env
    image              = var.image
    spark_code_uri     = var.spark_code_uri
    lake_bucket        = var.lake_bucket
    emr_application_id = var.emr_application_id
    emr_job_role_arn   = var.emr_job_role_arn
    snowflake_account  = var.snowflake_account
    snowflake_database = var.snowflake_database
    compose_version    = var.compose_version
    compose_sha256     = var.compose_sha256
    ecr_repository_url = var.ecr_repository_url
  })

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only
    # Containers reach the instance's credentials through Docker's bridge: one extra network
    # hop. With AWS's default limit of 1, every container would find no credentials.
    http_put_response_hop_limit = 2
  }

  # T instances default to "unlimited": sustained CPU then bills extra, silently.
  credit_specification {
    cpu_credits = "standard"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  tags = { Name = "earnings-watch-${var.env}-airflow" }

  # "Latest Amazon Linux" changes weekly, and the bootstrap only runs on first boot: neither
  # should replace a running host behind your back. Rebuilding is deliberate:
  #   terraform apply -replace=module.airflow_host.aws_instance.airflow
  lifecycle {
    ignore_changes = [ami, user_data]
  }
}
