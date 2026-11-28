#!/bin/sh
# Pre-deploy backup freshness gate from the backup markers (R08-06, DEPLOY_BACKUP_GATE=marker).
#
# Runs `python scripts/check_backup_freshness.py` inside the running api container on the
# deploy host, over SSH (ssh_common.sh, pinned host key). The check reads
# <BACKUP_PREFIX>/<kind>/latest.json in the backup bucket for every kind in BACKUP_KINDS and
# fails when any is missing or older than DEPLOY_BACKUP_MAX_AGE_HOURS (default 26). The
# container's own env file supplies BACKUP_BUCKET and the BACKUP_S3_* credentials; nothing
# secret passes through this script. Output is one line per kind (status and age only).
#
# Switch to this gate only after a release that ships scripts/check_backup_freshness.py is
# running on the host and the markers are fresh (docs/runbooks/BACKUP_AND_RESTORE.md).
#
#   DEPLOY_SSH_HOST DEPLOY_SSH_USER DEPLOY_SSH_PRIVATE_KEY DEPLOY_APP_PATH \
#   [DEPLOY_ENVIRONMENT=production] [DEPLOY_BACKUP_MAX_AGE_HOURS=26] \
#   deploy/scripts/check_backup_markers.sh
set -eu

required_vars="DEPLOY_SSH_HOST DEPLOY_SSH_USER DEPLOY_SSH_PRIVATE_KEY DEPLOY_APP_PATH"
for var_name in $required_vars; do
  eval "value=\${$var_name:-}"
  if [ -z "$value" ]; then
    echo "Missing required variable: $var_name" >&2
    exit 1
  fi
done

environment_name="${DEPLOY_ENVIRONMENT:-production}"
case "$environment_name" in
  staging | production) ;;
  *)
    echo "DEPLOY_ENVIRONMENT must be staging or production" >&2
    exit 1
    ;;
esac

max_age_hours="${DEPLOY_BACKUP_MAX_AGE_HOURS:-26}"
# Digits only, no leading zero (rejects 0 and octal-looking values like 010).
case "$max_age_hours" in
  '' | *[!0-9]* | 0*)
    echo "DEPLOY_BACKUP_MAX_AGE_HOURS must be a positive integer" >&2
    exit 1
    ;;
esac

# Wrap a value in single quotes for the remote shell, escaping embedded quotes.
shell_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}

compose_file="docker-compose.${environment_name}.yml"
remote_script="$(
  printf '%s\n' \
    "set -eu" \
    "cd $(shell_quote "$DEPLOY_APP_PATH")" \
    "docker compose -f $(shell_quote "$compose_file") exec -T api python scripts/check_backup_freshness.py --max-age-hours $max_age_hours"
)"

if [ "${DEPLOY_BACKUP_CHECK_PRINT_ONLY:-false}" = "true" ]; then
  # Local testing aid: print the remote script instead of connecting.
  printf '%s\n' "$remote_script"
  exit 0
fi

. "$(dirname "$0")/ssh_common.sh"
rudix_ssh_setup "$environment_name"
trap rudix_ssh_cleanup EXIT

# The script is sent on stdin so the path never passes through ssh argument parsing.
# shellcheck disable=SC2086
if ! printf '%s\n' "$remote_script" | ssh $ssh_opts "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST" sh -s; then
  echo "Backup marker freshness check failed (max age ${max_age_hours} h)." >&2
  exit 1
fi

echo "Backup markers verified (every configured kind within ${max_age_hours} h)."
