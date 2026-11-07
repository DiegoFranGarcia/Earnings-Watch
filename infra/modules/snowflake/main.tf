# The Snowflake warehouse's skeleton: databases, schemas, warehouses, functional roles, grants.
# One Snowflake account serves every environment, so these objects are account-wide.

locals {
  schemas = ["RAW", "STAGING", "INTERMEDIATE", "MARTS", "SNAPSHOTS", "AUDIT"]

  # Every (database, schema) pair, keyed "DATABASE.SCHEMA".
  database_schemas = {
    for pair in setproduct(var.databases, local.schemas) :
    "${pair[0]}.${pair[1]}" => { database = pair[0], schema = pair[1] }
  }

  # Extra-small, suspended after 60 idle seconds, with a hard limit on any one statement.
  warehouses = {
    WH_LOAD      = { timeout = 3600, comment = "COPY INTO from S3 (LOADER)" }
    WH_TRANSFORM = { timeout = 3600, comment = "dbt builds (TRANSFORMER)" }
    WH_REPORTING = { timeout = 300, comment = "Dashboard queries (REPORTER)" }
  }

  roles = {
    LOADER      = { warehouse = "WH_LOAD", comment = "Loads RAW from S3; writes load audit rows" }
    TRANSFORMER = { warehouse = "WH_TRANSFORM", comment = "Reads RAW; dbt builds everything downstream" }
    REPORTER    = { warehouse = "WH_REPORTING", comment = "Reads MARTS only" }
  }

  # Privileges on schemas, per role. Objects a role creates, it owns.
  schema_privileges = {
    "LOADER.RAW"               = ["USAGE", "CREATE TABLE"]
    "LOADER.AUDIT"             = ["USAGE", "CREATE TABLE"]
    "TRANSFORMER.RAW"          = ["USAGE"]
    "TRANSFORMER.STAGING"      = ["USAGE", "CREATE TABLE", "CREATE VIEW"]
    "TRANSFORMER.INTERMEDIATE" = ["USAGE", "CREATE TABLE", "CREATE VIEW"]
    "TRANSFORMER.MARTS"        = ["USAGE", "CREATE TABLE", "CREATE VIEW"]
    "TRANSFORMER.SNAPSHOTS"    = ["USAGE", "CREATE TABLE", "CREATE VIEW"]
    "TRANSFORMER.AUDIT"        = ["USAGE", "CREATE TABLE"]
    "REPORTER.MARTS"           = ["USAGE"]
  }

  # Read access to tables and views someone else owns, now and in future.
  read_grants = {
    "TRANSFORMER.RAW.TABLES" = { role = "TRANSFORMER", schema = "RAW", plural = "TABLES" }
    "REPORTER.MARTS.TABLES"  = { role = "REPORTER", schema = "MARTS", plural = "TABLES" }
    "REPORTER.MARTS.VIEWS"   = { role = "REPORTER", schema = "MARTS", plural = "VIEWS" }
  }

  # Expand the per-role maps across every granted database.
  database_usage = {
    for pair in setproduct(keys(local.roles), var.granted_databases) :
    "${pair[0]}.${pair[1]}" => { role = pair[0], database = pair[1] }
  }
  schema_grants = {
    for pair in setproduct(keys(local.schema_privileges), var.granted_databases) :
    "${pair[0]}@${pair[1]}" => {
      role       = split(".", pair[0])[0]
      schema     = "${pair[1]}.${split(".", pair[0])[1]}"
      privileges = local.schema_privileges[pair[0]]
    }
  }
  object_reads = {
    for pair in setproduct(keys(local.read_grants), var.granted_databases) :
    "${pair[0]}@${pair[1]}" => merge(local.read_grants[pair[0]], {
      schema = "${pair[1]}.${local.read_grants[pair[0]].schema}"
    })
  }
}

# -- databases and schemas ---------------------------------------------------------

resource "snowflake_database" "this" {
  for_each = toset(var.databases)

  name                           = each.value
  is_transient                   = each.value == "EARNINGSWATCH_CI" # CI data is disposable
  data_retention_time_in_days    = 1
  drop_public_schema_on_creation = true
  comment                        = "EarningsWatch (managed by Terraform)"
}

resource "snowflake_schema" "this" {
  for_each = local.database_schemas

  database = snowflake_database.this[each.value.database].name
  name     = each.value.schema
  comment  = "Managed by Terraform"
}

# -- warehouses --------------------------------------------------------------------

resource "snowflake_warehouse" "this" {
  for_each = local.warehouses

  name                         = each.key
  warehouse_size               = "XSMALL"
  auto_suspend                 = 60
  auto_resume                  = "true"
  initially_suspended          = true
  statement_timeout_in_seconds = each.value.timeout
  comment                      = each.value.comment
}

# -- functional roles --------------------------------------------------------------

resource "snowflake_account_role" "this" {
  for_each = local.roles

  name    = each.key
  comment = each.value.comment
}

# Admins can see and manage everything the functional roles own.
resource "snowflake_grant_account_role" "to_sysadmin" {
  for_each = local.roles

  role_name        = snowflake_account_role.this[each.key].name
  parent_role_name = "SYSADMIN"
}

resource "snowflake_grant_privileges_to_account_role" "warehouse_usage" {
  for_each = local.roles

  account_role_name = snowflake_account_role.this[each.key].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.this[each.value.warehouse].name
  }
}

resource "snowflake_grant_privileges_to_account_role" "database_usage" {
  for_each = local.database_usage

  account_role_name = snowflake_account_role.this[each.value.role].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.this[each.value.database].name
  }
}

resource "snowflake_grant_privileges_to_account_role" "schema" {
  for_each = local.schema_grants

  account_role_name = snowflake_account_role.this[each.value.role].name
  privileges        = each.value.privileges
  on_schema {
    schema_name = snowflake_schema.this[each.value.schema].fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "read_existing" {
  for_each = local.object_reads

  account_role_name = snowflake_account_role.this[each.value.role].name
  privileges        = ["SELECT"]
  on_schema_object {
    all {
      object_type_plural = each.value.plural
      in_schema          = snowflake_schema.this[each.value.schema].fully_qualified_name
    }
  }
}

# Future grants: tables and views created later (by loads or dbt) are readable at once.
resource "snowflake_grant_privileges_to_account_role" "read_future" {
  for_each = local.object_reads

  account_role_name = snowflake_account_role.this[each.value.role].name
  privileges        = ["SELECT"]
  on_schema_object {
    future {
      object_type_plural = each.value.plural
      in_schema          = snowflake_schema.this[each.value.schema].fully_qualified_name
    }
  }
}

# -- service users -----------------------------------------------------------------

locals {
  # A .pub file minus its "-----BEGIN/END PUBLIC KEY-----" lines, as the one line Snowflake wants.
  public_keys = {
    for name, user in var.service_users : name => join("", [
      for line in split("\n", trimspace(file(pathexpand(user.public_key_path)))) :
      trimspace(line) if !startswith(trimspace(line), "-----")
    ])
  }
}

resource "snowflake_service_user" "this" {
  for_each = var.service_users

  name              = each.key
  default_role      = snowflake_account_role.this[each.value.role].name
  default_warehouse = snowflake_warehouse.this[each.value.warehouse].name
  rsa_public_key    = local.public_keys[each.key]
  comment           = "Key-pair login only; role ${each.value.role}"
}

resource "snowflake_grant_account_role" "service_user" {
  for_each = var.service_users

  role_name = snowflake_account_role.this[each.value.role].name
  user_name = snowflake_service_user.this[each.key].name
}
