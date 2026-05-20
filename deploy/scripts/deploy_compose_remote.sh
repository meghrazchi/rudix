#!/bin/sh
set -eu

environment_name="${1:-}"
if [ -z "$environment_name" ]; then
  echo "Usage: $0 <staging|production>" >&2
  exit 1
fi

required_vars="DEPLOY_SSH_HOST DEPLOY_SSH_USER DEPLOY_SSH_PRIVATE_KEY DEPLOY_APP_PATH DEPLOY_ENV_FILE_CONTENT DEPLOY_REGISTRY DEPLOY_REGISTRY_USER DEPLOY_REGISTRY_PASSWORD DEPLOY_API_IMAGE DEPLOY_WORKER_IMAGE DEPLOY_FRONTEND_IMAGE"
for var_name in $required_vars; do
  eval "value=\${$var_name:-}"
  if [ -z "$value" ]; then
    echo "Missing required variable: $var_name" >&2
    exit 1
  fi
done

compose_file="docker-compose.${environment_name}.yml"
compose_source="deploy/compose/${compose_file}"
if [ ! -f "$compose_source" ]; then
  echo "Compose template not found: $compose_source" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

cp "$compose_source" "$tmp_dir/$compose_file"
printf '%s\n' "$DEPLOY_ENV_FILE_CONTENT" > "$tmp_dir/.env"
cat >> "$tmp_dir/.env" <<EOF
RUDIX_API_IMAGE=$DEPLOY_API_IMAGE
RUDIX_WORKER_IMAGE=$DEPLOY_WORKER_IMAGE
RUDIX_FRONTEND_IMAGE=$DEPLOY_FRONTEND_IMAGE
EOF

install -m 700 -d "$HOME/.ssh"
printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY" > "$HOME/.ssh/rudix_deploy_key"
chmod 600 "$HOME/.ssh/rudix_deploy_key"

ssh_opts="-i $HOME/.ssh/rudix_deploy_key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p ${DEPLOY_SSH_PORT:-22}"

ssh $ssh_opts "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST" "mkdir -p '$DEPLOY_APP_PATH'"
scp $ssh_opts "$tmp_dir/$compose_file" "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST:$DEPLOY_APP_PATH/$compose_file"
scp $ssh_opts "$tmp_dir/.env" "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST:$DEPLOY_APP_PATH/.env"

ssh $ssh_opts "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST" "
  set -eu
  cd '$DEPLOY_APP_PATH'
  echo '$DEPLOY_REGISTRY_PASSWORD' | docker login -u '$DEPLOY_REGISTRY_USER' --password-stdin '$DEPLOY_REGISTRY'
  docker compose -f '$compose_file' pull
  docker compose -f '$compose_file' run --rm api alembic upgrade head
  docker compose -f '$compose_file' up -d
  curl -fsS http://127.0.0.1:8000/api/v1/health >/dev/null
  curl -fsS http://127.0.0.1:8000/api/v1/ready >/dev/null
"

echo "Remote deployment completed for ${environment_name}."
