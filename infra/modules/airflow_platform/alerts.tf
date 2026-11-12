# Alarms are published here and emailed. Part of the platform, not the host, so the subscription
# (which AWS asks you to confirm by email) survives a rebuild of the host.

resource "aws_sns_topic" "alerts" {
  name = "earnings-watch-${var.env}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
