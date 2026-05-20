#!/bin/sh
set -eu

required_vars="DEPLOY_SSH_HOST DEPLOY_SSH_USER DEPLOY_SSH_PRIVATE_KEY DEPLOY_POSTGRES_BACKUP_PATH DEPLOY_MINIO_BACKUP_PATH DEPLOY_QDRANT_BACKUP_PATH"
for var_name in $required_vars; do
  eval "value=\${$var_name:-}"
  if [ -z "$value" ]; then
    echo "Missing required variable: $var_name" >&2
    exit 1
  fi
done

install -m 700 -d "$HOME/.ssh"
printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY" > "$HOME/.ssh/rudix_deploy_key"
chmod 600 "$HOME/.ssh/rudix_deploy_key"
ssh_opts="-i $HOME/.ssh/rudix_deploy_key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p ${DEPLOY_SSH_PORT:-22}"

ssh $ssh_opts "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST" "
  set -eu
  test -f '$DEPLOY_POSTGRES_BACKUP_PATH'
  test -f '$DEPLOY_MINIO_BACKUP_PATH'
  test -f '$DEPLOY_QDRANT_BACKUP_PATH'
"

echo "Remote backup artifacts verified."
