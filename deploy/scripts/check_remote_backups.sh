#!/bin/sh
# Pre-deploy backup freshness gate.
#
# Each DEPLOY_*_BACKUP_PATH may be a single backup file or a directory of
# timestamped backups. The gate requires the path to exist on the remote host
# and to contain at least one regular file modified within
# DEPLOY_BACKUP_MAX_AGE_HOURS (default 26). Only the failing path's label
# (postgres, minio, qdrant) is reported; paths and file listings are never printed.
set -eu

required_vars="DEPLOY_SSH_HOST DEPLOY_SSH_USER DEPLOY_SSH_PRIVATE_KEY DEPLOY_POSTGRES_BACKUP_PATH DEPLOY_MINIO_BACKUP_PATH DEPLOY_QDRANT_BACKUP_PATH"
for var_name in $required_vars; do
  eval "value=\${$var_name:-}"
  if [ -z "$value" ]; then
    echo "Missing required variable: $var_name" >&2
    exit 1
  fi
done

max_age_hours="${DEPLOY_BACKUP_MAX_AGE_HOURS:-26}"
# Digits only, no leading zero (rejects 0 and octal-looking values like 010).
case "$max_age_hours" in
  '' | *[!0-9]* | 0*)
    echo "DEPLOY_BACKUP_MAX_AGE_HOURS must be a positive integer" >&2
    exit 1
    ;;
esac
max_age_minutes=$((max_age_hours * 60))

# Wrap a value in single quotes for the remote shell, escaping embedded quotes.
shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

# Builds the remote command for one path. The label is a fixed identifier.
# find -H follows the path itself when it is a symlink (e.g. latest.dump ->
# a timestamped dump), as the previous `test -f` gate did.
remote_check() {
  label="$1"
  quoted_path="$(shell_quote "$2")"
  printf '%s\n' \
    "p=$quoted_path" \
    "if ! { test -e \"\$p\" && find -H \"\$p\" -type f -mmin -$max_age_minutes -print -quit | grep -q .; }; then" \
    "  echo \"Backup check failed for $label: no file newer than $max_age_hours h\" >&2" \
    "  failed=1" \
    "fi"
}

remote_script="$(
  printf '%s\n' "failed=0"
  remote_check postgres "$DEPLOY_POSTGRES_BACKUP_PATH"
  remote_check minio "$DEPLOY_MINIO_BACKUP_PATH"
  remote_check qdrant "$DEPLOY_QDRANT_BACKUP_PATH"
  printf '%s\n' 'exit "$failed"'
)"

if [ "${DEPLOY_BACKUP_CHECK_PRINT_ONLY:-false}" = "true" ]; then
  # Local testing aid: print the remote script instead of connecting.
  printf '%s\n' "$remote_script"
  exit 0
fi

# Pinned host key (PRODUCTION_SSH_KNOWN_HOSTS or DEPLOY_SSH_KNOWN_HOSTS); see ssh_common.sh.
. "$(dirname "$0")/ssh_common.sh"
rudix_ssh_setup "${DEPLOY_ENVIRONMENT:-production}"
trap rudix_ssh_cleanup EXIT

# The script is sent on stdin so paths never pass through ssh argument parsing.
# shellcheck disable=SC2086
if ! printf '%s\n' "$remote_script" | ssh $ssh_opts "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST" sh -s; then
  echo "Remote backup freshness check failed (max age ${max_age_hours} h)." >&2
  exit 1
fi

echo "Remote backup artifacts verified (newest file within ${max_age_hours} h for each path)."
