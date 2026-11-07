output "integration" {
  value = snowflake_storage_integration_aws.lake.name
}

output "stage" {
  value = snowflake_stage_external_s3.silver.fully_qualified_name
}

output "snowflake_read_role_arn" {
  value = aws_iam_role.snowflake.arn
}
