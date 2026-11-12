# Alarms on the host, emailed through the platform's topic. While the host is stopped (20 hours a
# day) these metrics have no data: that is treated as fine, so the daily stop never alarms.

resource "aws_cloudwatch_metric_alarm" "status_check" {
  alarm_name          = "earnings-watch-${var.env}-airflow-status-check"
  alarm_description   = "The Airflow host failed its EC2 status checks"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  dimensions          = { InstanceId = aws_instance.airflow.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
  ok_actions          = [var.alerts_topic_arn]
}

# Yesterday's lesson: a host stuck at its CPU baseline earns no credits, and then cannot deploy.
# Warn while there is still time to act.
resource "aws_cloudwatch_metric_alarm" "cpu_credits_low" {
  alarm_name          = "earnings-watch-${var.env}-airflow-cpu-credits-low"
  alarm_description   = "The Airflow host's CPU credit balance has stayed low: it is being throttled"
  namespace           = "AWS/EC2"
  metric_name         = "CPUCreditBalance"
  dimensions          = { InstanceId = aws_instance.airflow.id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 6 # 30 minutes
  threshold           = 10
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alerts_topic_arn]
}
