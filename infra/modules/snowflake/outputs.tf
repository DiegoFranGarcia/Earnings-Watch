output "databases" {
  value = [for d in snowflake_database.this : d.name]
}

output "warehouses" {
  value = [for w in snowflake_warehouse.this : w.name]
}

output "roles" {
  value = [for r in snowflake_account_role.this : r.name]
}

output "schemas" {
  description = "Schemas by DATABASE.SCHEMA; referencing them makes dependents wait for them."
  value       = { for k, s in snowflake_schema.this : k => { database = s.database, name = s.name } }
}

output "role_names" {
  value = { for k, r in snowflake_account_role.this : k => r.name }
}

output "service_users" {
  value = [for u in snowflake_service_user.this : u.name]
}
