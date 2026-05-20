#!/bin/sh
set -eu

required_vars="DEPLOY_SSH_HOST DEPLOY_SSH_USER DEPLOY_SSH_PRIVATE_KEY DEPLOY_APP_PATH DEPLOY_REGISTRY DEPLOY_REGISTRY_USER DEPLOY_REGISTRY_PASSWORD ROLLBACK_API_IMAGE ROLLBACK_WORKER_IMAGE ROLLBACK_FRONTEND_IMAGE"
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

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

cat > "$tmp_dir/.rollback-images.env" <<EOF
RUDIX_API_IMAGE=$ROLLBACK_API_IMAGE
RUDIX_WORKER_IMAGE=$ROLLBACK_WORKER_IMAGE
RUDIX_FRONTEND_IMAGE=$ROLLBACK_FRONTEND_IMAGE
EOF

scp $ssh_opts "$tmp_dir/.rollback-images.env" "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST:$DEPLOY_APP_PATH/.rollback-images.env"

ssh $ssh_opts "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST" "
  set -eu
  cd '$DEPLOY_APP_PATH'
  echo '$DEPLOY_REGISTRY_PASSWORD' | docker login -u '$DEPLOY_REGISTRY_USER' --password-stdin '$DEPLOY_REGISTRY'
  . ./.rollback-images.env
  cp .env .env.rollback.tmp
  grep -v '^RUDIX_.*_IMAGE=' .env.rollback.tmp > .env
  cat .rollback-images.env >> .env
  rm -f .env.rollback.tmp
  docker compose -f docker-compose.production.yml pull
  docker compose -f docker-compose.production.yml up -d
  curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null
"

echo "Rollback deployment completed."
