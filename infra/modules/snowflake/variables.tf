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
