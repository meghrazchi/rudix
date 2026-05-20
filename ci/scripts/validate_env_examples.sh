#!/bin/sh
set -eu

check_keys() {
  file="$1"
  shift
  if [ ! -f "$file" ]; then
    echo "Skipping check for missing file: ${file}"
    return 0
  fi
  for key in "$@"; do
    if ! grep -Eq "^${key}=" "$file"; then
      echo "Missing required key '${key}' in ${file}" >&2
      exit 1
    fi
  done
}

check_keys ".env.example" \
  "DATABASE_URL" \
  "OPENAI_API_KEY" \
  "AUTH_PROVIDER" \
  "APP_AUTH_SECRET" \
  "QDRANT_URL" \
  "MINIO_ENDPOINT" \
  "RABBITMQ_URL" \
  "REDIS_URL"

if [ -f "frontend/.env.example" ]; then
  check_keys "frontend/.env.example" \
    "NEXT_PUBLIC_API_URL" \
    "NEXT_PUBLIC_APP_URL" \
    "NEXT_PUBLIC_AUTH_PROVIDER" \
    "NEXT_PUBLIC_CHAT_AGENTIC_ENABLED" \
    "NEXT_PUBLIC_AUTH_REFRESH_URL" \
    "NEXT_PUBLIC_AUTH_LOGOUT_URL"
else
  echo "frontend/.env.example not found in this pipeline context; skipping frontend env key checks."
fi

echo "Environment example files include required runtime keys."
