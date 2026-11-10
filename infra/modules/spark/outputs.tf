output "application_id" {
  description = "Pass to StartJobRun to run a Spark job on this application."
  value       = aws_emrserverless_application.spark.id
}

output "job_role_arn" {
  description = "The role Spark jobs run as."
  value       = aws_iam_role.job.arn
}

output "application_arn" {
  description = "For IAM policies that allow running jobs on this application only."
  value       = aws_emrserverless_application.spark.arn
}
