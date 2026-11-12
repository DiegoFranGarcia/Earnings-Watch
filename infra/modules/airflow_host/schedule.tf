# Run the host four hours a day: the daily DAGs need that, not 24. About $8 a month instead of $49.
# EventBridge Scheduler calls EC2 directly, through a role that can start and stop this instance
# and nothing else.

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "earnings-watch-${var.env}-airflow-schedule"
  description        = "Starts and stops the Airflow host on a schedule"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

data "aws_iam_policy_document" "start_stop" {
  statement {
    actions   = ["ec2:StartInstances", "ec2:StopInstances"]
    resources = [aws_instance.airflow.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "start-stop-the-airflow-host"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.start_stop.json
}

resource "aws_scheduler_schedule" "start" {
  name                         = "earnings-watch-${var.env}-airflow-start"
  description                  = "Start the Airflow host before the 06:00 UTC daily run"
  schedule_expression          = var.start_cron
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:startInstances"
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ InstanceIds = [aws_instance.airflow.id] })
  }
}

resource "aws_scheduler_schedule" "stop" {
  name                         = "earnings-watch-${var.env}-airflow-stop"
  description                  = "Stop the Airflow host after the 09:00 deadline and 09:30 backup"
  schedule_expression          = var.stop_cron
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:ec2:stopInstances"
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ InstanceIds = [aws_instance.airflow.id] })
  }
}
