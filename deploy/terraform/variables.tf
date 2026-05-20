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

variable "backup_check_enabled" {
  description = "Whether to enforce remote backup artifact checks before deployment."
  type        = bool
  default     = false
}

variable "postgres_backup_path" {
  description = "Remote path to PostgreSQL backup artifact."
  type        = string
  default     = ""
}

variable "minio_backup_path" {
  description = "Remote path to MinIO backup artifact."
  type        = string
  default     = ""
}

variable "qdrant_backup_path" {
  description = "Remote path to Qdrant snapshot artifact."
  type        = string
  default     = ""
}
