variable "databases" {
  description = "Databases to create, each with the standard schemas. CI's is transient."
  type        = list(string)
  default     = ["EARNINGSWATCH", "EARNINGSWATCH_DEV", "EARNINGSWATCH_CI"]
}

variable "granted_databases" {
  description = "Databases the LOADER, TRANSFORMER and REPORTER roles work in (CI gets its own role in Stage 8)."
  type        = list(string)
  default     = ["EARNINGSWATCH", "EARNINGSWATCH_DEV"]
}

variable "service_users" {
  description = "Machine users: a default role and warehouse each, key-pair login only. extra_roles are granted too, for a program that needs a second, narrower identity, chosen when it connects."
  type = map(object({
    role            = string
    warehouse       = string
    public_key_path = string
    extra_roles     = optional(list(string), [])
  }))
  default = {}
}
