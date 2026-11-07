terraform {
  required_providers {
    # Not a HashiCorp provider, so every module that uses it must name its source;
    # the exact version is pinned once, in the root (infra/envs/dev/versions.tf).
    snowflake = {
      source = "snowflakedb/snowflake"
    }
  }
}
