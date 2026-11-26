#!/bin/sh
# Shared SSH setup for the deploy scripts (R03-08). Source it, then call:
#
#   . "$(dirname "$0")/ssh_common.sh"
#   rudix_ssh_setup <staging|production>
#   trap rudix_ssh_cleanup EXIT
#
# Host keys are pinned. The known_hosts content comes from <ENV>_SSH_KNOWN_HOSTS
# (STAGING_SSH_KNOWN_HOSTS / PRODUCTION_SSH_KNOWN_HOSTS secrets), or from
# DEPLOY_SSH_KNOWN_HOSTS when the caller maps it generically. An empty value is a
# hard failure: there is no trust-on-first-use fallback.
#
# The private key comes from DEPLOY_SSH_PRIVATE_KEY and the port from
# DEPLOY_SSH_PORT (default 22). Both files are written to a private temp dir.
#
# Exports:
#   ssh_opts  options for ssh (-p port)
#   scp_opts  options for scp (-P port)
#   RUDIX_SSH_KNOWN_HOSTS_FILE, RUDIX_SSH_KEY_FILE

rudix_ssh_cleanup() {
  if [ -n "${RUDIX_SSH_DIR:-}" ] && [ -d "$RUDIX_SSH_DIR" ]; then
    rm -rf "$RUDIX_SSH_DIR"
  fi
}

rudix_ssh_setup() {
  rudix_env="${1:-${DEPLOY_ENVIRONMENT:-}}"
  case "$rudix_env" in
    staging | production) ;;
    *)
      echo "rudix_ssh_setup: environment must be staging or production" >&2
      return 2
      ;;
  esac

  rudix_env_upper="$(printf '%s' "$rudix_env" | tr '[:lower:]' '[:upper:]')"
  rudix_known_hosts_var="${rudix_env_upper}_SSH_KNOWN_HOSTS"
  eval "rudix_known_hosts=\${$rudix_known_hosts_var:-}"
  if [ -z "$rudix_known_hosts" ]; then
    rudix_known_hosts="${DEPLOY_SSH_KNOWN_HOSTS:-}"
  fi
  if [ -z "$rudix_known_hosts" ]; then
    echo "Missing ${rudix_known_hosts_var} (pinned known_hosts lines for the ${rudix_env} host)." >&2
    return 1
  fi
  if [ -z "${DEPLOY_SSH_PRIVATE_KEY:-}" ]; then
    echo "Missing DEPLOY_SSH_PRIVATE_KEY." >&2
    return 1
  fi

  rudix_port="${DEPLOY_SSH_PORT:-22}"
  case "$rudix_port" in
    '' | *[!0-9]*)
      echo "DEPLOY_SSH_PORT must be a number" >&2
      return 1
      ;;
  esac

  RUDIX_SSH_DIR="$(mktemp -d)"
  chmod 700 "$RUDIX_SSH_DIR"
  RUDIX_SSH_KNOWN_HOSTS_FILE="$RUDIX_SSH_DIR/known_hosts"
  RUDIX_SSH_KEY_FILE="$RUDIX_SSH_DIR/deploy_key"
  (
    umask 077
    printf '%s\n' "$rudix_known_hosts" > "$RUDIX_SSH_KNOWN_HOSTS_FILE"
    printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY" > "$RUDIX_SSH_KEY_FILE"
  )
  unset rudix_known_hosts

  rudix_common_opts="-i $RUDIX_SSH_KEY_FILE -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$RUDIX_SSH_KNOWN_HOSTS_FILE -o BatchMode=yes"
  ssh_opts="$rudix_common_opts -p $rudix_port"
  scp_opts="$rudix_common_opts -P $rudix_port"
  export ssh_opts scp_opts RUDIX_SSH_DIR RUDIX_SSH_KNOWN_HOSTS_FILE RUDIX_SSH_KEY_FILE
}
