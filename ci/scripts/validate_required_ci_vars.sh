#!/bin/sh
set -eu

target="${1:-}"
if [ -z "$target" ]; then
  echo "Usage: $0 <staging|production>" >&2
  exit 1
fi

validate_vars() {
  env_name="$1"
  shift
  missing=0
  for var_name in "$@"; do
    eval "var_value=\${$var_name:-}"
    if [ -z "$var_value" ]; then
      echo "Missing required CI variable for ${env_name}: ${var_name}" >&2
      missing=1
    fi
  done
  if [ "$missing" -ne 0 ]; then
    exit 1
  fi
}

case "$target" in
  staging)
    validate_vars "staging" \
      STAGING_SSH_HOST \
      STAGING_SSH_USER \
      STAGING_SSH_PRIVATE_KEY \
      STAGING_APP_PATH \
      STAGING_ENV_FILE \
      STAGING_ENV_URL
    ;;
  production)
    validate_vars "production" \
      PRODUCTION_SSH_HOST \
      PRODUCTION_SSH_USER \
      PRODUCTION_SSH_PRIVATE_KEY \
      PRODUCTION_APP_PATH \
      PRODUCTION_ENV_FILE \
      PRODUCTION_ENV_URL \
      PRODUCTION_POSTGRES_BACKUP_PATH \
      PRODUCTION_MINIO_BACKUP_PATH \
      PRODUCTION_QDRANT_BACKUP_PATH
    ;;
  *)
    echo "Unknown target '$target'. Expected staging or production." >&2
    exit 1
    ;;
esac

echo "Required CI variables are configured for ${target}."
