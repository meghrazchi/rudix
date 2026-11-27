variable "environment_name" {
  description = "Target environment name (staging or production)."
  type        = string
}

variable "compose_file_path" {
  description = "Path to the environment-specific compose file in the repository."
  type        = string
}

variable "ssh_host" {
  description = "Remote deployment host."
  type        = string
}

variable "ssh_port" {
  description = "Remote SSH port."
  type        = number
  default     = 22
}

variable "ssh_user" {
  description = "Remote SSH user."
  type        = string
}

variable "ssh_host_key" {
  description = "Pinned public host key of the deploy host, \"<type> <base64>\" (fields 2 and 3 of its known_hosts line). No default: an unpinned connection is refused."
  type        = string

  validation {
    condition     = length(regexall("^[a-z0-9@.-]+ [A-Za-z0-9+/=]+$", trimspace(var.ssh_host_key))) == 1
    error_message = "ssh_host_key must look like \"ssh-ed25519 AAAA...\" (key type and base64, no host field)."
  }
}

variable "ssh_private_key" {
  description = "SSH private key used for deployment."
  type        = string
  sensitive   = true
}

variable "app_path" {
  description = "Deployment directory on the remote host."
  type        = string
}

variable "registry" {
  description = "Container registry hostname."
  type        = string
}

variable "registry_user" {
  description = "Container registry user."
  type        = string
}

variable "registry_password" {
  description = "Container registry password/token."
  type        = string
  sensitive   = true
}

variable "env_file_content" {
  description = "Rendered runtime .env file content for the target environment."
  type        = string
  sensitive   = true
}

variable "api_image" {
  description = "API image reference (digest preferred)."
  type        = string
}

variable "worker_image" {
  description = "Worker image reference (digest preferred)."
  type        = string
}

variable "frontend_image" {
  description = "Frontend image reference (digest preferred)."
  type        = string
}

variable "migration_command" {
  description = "Migration command executed in the API service container."
  type        = string
  default     = "alembic upgrade head"
}

variable "health_url" {
  description = "Health endpoint checked after rollout."
  type        = string
  default     = "http://127.0.0.1:8000/api/v1/health"
}

variable "readiness_url" {
  description = "Readiness endpoint checked after rollout."
  type        = string
  default     = "http://127.0.0.1:8000/api/v1/ready"
}

variable "bootstrap_admin_email" {
  description = "Email for the first admin account, created only if the database has no organizations yet. Leave empty to skip bootstrap."
  type        = string
  default     = ""
}

variable "bootstrap_admin_password" {
  description = "Password for the first admin account. Leave empty to skip bootstrap."
  type        = string
  sensitive   = true
  default     = ""
}

variable "neo4j_username" {
  description = "Username for the Enterprise Graph Neo4j instance."
  type        = string
  default     = "neo4j"
}

variable "neo4j_password" {
  description = "Password for the Enterprise Graph Neo4j instance. Leave empty to skip enabling Enterprise Graph."
  type        = string
  sensitive   = true
  default     = ""
}

variable "backup_check_enabled" {
  description = "Deprecated: the backup gate now runs in the release workflow (deploy/scripts/check_remote_backups.sh). Still set by release.yml; kept as a rollout trigger only."
  type        = bool
  default     = false
}

variable "postgres_backup_path" {
  description = "Deprecated: unused by Terraform; the release workflow checks backups. Still set by release.yml."
  type        = string
  default     = ""
}

variable "minio_backup_path" {
  description = "Deprecated: unused by Terraform; the release workflow checks backups. Still set by release.yml."
  type        = string
  default     = ""
}

variable "qdrant_backup_path" {
  description = "Deprecated: unused by Terraform; the release workflow checks backups. Still set by release.yml."
  type        = string
  default     = ""
}

variable "infra_services" {
  description = "Space-separated services started with --wait before migrations. Must name only services defined in the environment's compose file."
  type        = string
  default     = "postgres rabbitmq redis minio qdrant"
}
