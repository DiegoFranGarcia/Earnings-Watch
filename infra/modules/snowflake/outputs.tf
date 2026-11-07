output "databases" {
  value = [for d in snowflake_database.this : d.name]
}

output "warehouses" {
  value = [for w in snowflake_warehouse.this : w.name]
}

output "roles" {
  value = [for r in snowflake_account_role.this : r.name]
}
