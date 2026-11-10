output "subnet_id" {
  value = aws_subnet.public.id
}

output "security_group_id" {
  value = aws_security_group.host.id
}

output "instance_profile_name" {
  value = aws_iam_instance_profile.host.name
}

output "host_role_arn" {
  value = aws_iam_role.host.arn
}

output "ecr_repository_url" {
  value = aws_ecr_repository.airflow.repository_url
}

output "secret_names" {
  value = { for key, secret in aws_secretsmanager_secret.host : key => secret.name }
}
