#!/bin/sh
# Pre-deploy check of the runtime env file for staging/production compose.
#
# Usage: DEPLOY_ENV_FILE_CONTENT="$ENV_FILE" check_deploy_env.sh <staging|production>
#
# The env file content is read from DEPLOY_ENV_FILE_CONTENT (KEY=VALUE lines;
# comments and blank lines ignored; the last occurrence of a key wins). Values
# are never printed, only key names.
#
# Checks:
#   - REDIS_PASSWORD is set and URL-safe ([A-Za-z0-9._~-]), because compose
#     embeds it in REDIS_URL without escaping.
#   - QDRANT_IMAGE, MINIO_IMAGE, RABBITMQ_IMAGE are set and pinned (an explicit
#     tag other than "latest", or a digest).
# Production: failures exit 1; image checks become warnings when
# DEPLOY_ALLOW_UNPINNED_IMAGES=true. Staging: every finding is a warning.
set -eu

target="${1:-}"
case "$target" in
  staging | production) ;;
  *)
    echo "Usage: $0 <staging|production>" >&2
    exit 2
    ;;
esac

if [ -z "${DEPLOY_ENV_FILE_CONTENT:-}" ]; then
  if [ "$target" = "staging" ]; then
    echo "WARNING: DEPLOY_ENV_FILE_CONTENT is empty; skipping the staging env check." >&2
    exit 0
  fi
  echo "ERROR: DEPLOY_ENV_FILE_CONTENT is empty; cannot check the production env file." >&2
  exit 1
fi

allow_unpinned="${DEPLOY_ALLOW_UNPINNED_IMAGES:-false}"
errors=0
warnings=0

# Prints the value of the last KEY=... line (export prefix and surrounding
# quotes stripped). Prints nothing when the key is absent.
env_value() {
  printf '%s\n' "$DEPLOY_ENV_FILE_CONTENT" | awk -v key="$1" '
    {
      sub(/\r$/, "")
      line = $0
      sub(/^[ \t]+/, "", line)
      if (line == "" || substr(line, 1, 1) == "#") next
      sub(/^export[ \t]+/, "", line)
      eq = index(line, "=")
      if (eq == 0) next
      k = substr(line, 1, eq - 1)
      sub(/[ \t]+$/, "", k)
      if (k != key) next
      v = substr(line, eq + 1)
      if (v ~ /^".*"$/ || v ~ /^\047.*\047$/) v = substr(v, 2, length(v) - 2)
      found = 1
      value = v
    }
    END { if (found) printf "%s", value }
  '
}

# report <error|warning> <message>
report() {
  if [ "$1" = "error" ]; then
    echo "ERROR: $2" >&2
    errors=$((errors + 1))
  else
    echo "WARNING: $2" >&2
    warnings=$((warnings + 1))
  fi
}

severity_for() {
  if [ "$target" = "staging" ]; then
    echo warning
  elif [ "$1" = "image" ] && [ "$allow_unpinned" = "true" ]; then
    echo warning
  else
    echo error
  fi
}

redis_password="$(env_value REDIS_PASSWORD)"
if [ -z "$redis_password" ]; then
  report "$(severity_for redis)" "REDIS_PASSWORD is not set in the ${target} env file"
elif ! printf '%s' "$redis_password" | grep -Eq '^[A-Za-z0-9._~-]+$'; then
  report "$(severity_for redis)" "REDIS_PASSWORD must contain only URL-safe characters [A-Za-z0-9._~-]"
fi
unset redis_password

for key in QDRANT_IMAGE MINIO_IMAGE RABBITMQ_IMAGE; do
  image="$(env_value "$key")"
  # Last path segment, so a registry port (host:5000/repo) is not read as a tag.
  last_segment="${image##*/}"
  if [ -z "$image" ]; then
    report "$(severity_for image)" "${key} is not set; pin the running version (tag or digest)"
  elif printf '%s' "$image" | grep -q '@sha256:'; then
    :
  elif [ "${last_segment#*:}" = "$last_segment" ]; then
    report "$(severity_for image)" "${key} has no tag or digest; pin an exact version"
  elif [ "${last_segment##*:}" = "latest" ]; then
    report "$(severity_for image)" "${key} uses :latest; pin an exact version"
  fi
done

echo "Deploy env check (${target}): ${errors} error(s), ${warnings} warning(s)."
if [ "$errors" -gt 0 ]; then
  exit 1
fi
