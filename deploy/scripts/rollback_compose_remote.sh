#!/bin/sh
# Rolls a compose deployment back to explicit image references. Never runs
# migrations: the database stays at its current Alembic revision (see
# DEPLOYMENT.md "13. Rollback" for when a downgrade is safe).
#
# DEPLOY_ENVIRONMENT selects the compose file and the pinned known_hosts secret
# (default production, the only target before R03-07).
set -eu

required_vars="DEPLOY_SSH_HOST DEPLOY_SSH_USER DEPLOY_SSH_PRIVATE_KEY DEPLOY_APP_PATH DEPLOY_REGISTRY DEPLOY_REGISTRY_USER DEPLOY_REGISTRY_PASSWORD ROLLBACK_API_IMAGE ROLLBACK_WORKER_IMAGE ROLLBACK_FRONTEND_IMAGE"
for var_name in $required_vars; do
  eval "value=\${$var_name:-}"
  if [ -z "$value" ]; then
    echo "Missing required variable: $var_name" >&2
    exit 1
  fi
done

environment_name="${DEPLOY_ENVIRONMENT:-production}"
compose_file="docker-compose.${environment_name}.yml"

# Pinned host key (<ENV>_SSH_KNOWN_HOSTS or DEPLOY_SSH_KNOWN_HOSTS); see ssh_common.sh.
. "$(dirname "$0")/ssh_common.sh"
rudix_ssh_setup "$environment_name"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"; rudix_ssh_cleanup' EXIT

cat > "$tmp_dir/.rollback-images.env" <<EOF
RUDIX_API_IMAGE=$ROLLBACK_API_IMAGE
RUDIX_WORKER_IMAGE=$ROLLBACK_WORKER_IMAGE
RUDIX_FRONTEND_IMAGE=$ROLLBACK_FRONTEND_IMAGE
EOF

# shellcheck disable=SC2086
scp $scp_opts "$tmp_dir/.rollback-images.env" "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST:$DEPLOY_APP_PATH/.rollback-images.env"

# The Alembic lines are informational: they print the database revision and the
# rollback image's head so an operator can see whether the schema is ahead of
# the code. Nothing is downgraded.
# shellcheck disable=SC2086
ssh $ssh_opts "$DEPLOY_SSH_USER@$DEPLOY_SSH_HOST" "
  set -eu
  cd '$DEPLOY_APP_PATH'
  echo '$DEPLOY_REGISTRY_PASSWORD' | docker login -u '$DEPLOY_REGISTRY_USER' --password-stdin '$DEPLOY_REGISTRY'
  . ./.rollback-images.env
  echo 'Database revision before rollback:'
  docker compose -f '$compose_file' exec -T api alembic current 2>/dev/null || echo '  (could not read alembic current)'
  cp .env .env.rollback.tmp
  grep -v '^RUDIX_.*_IMAGE=' .env.rollback.tmp > .env
  cat .rollback-images.env >> .env
  rm -f .env.rollback.tmp
  docker compose -f '$compose_file' pull
  echo 'Alembic head of the rollback image:'
  docker compose -f '$compose_file' run --rm --no-deps api alembic heads 2>/dev/null || echo '  (could not read alembic heads)'
  # --wait: the health check below runs once every started service is running or healthy.
  docker compose -f '$compose_file' up -d --wait
  # Port 8000 is no longer published on the host (R08-01): check inside the api container.
  docker compose -f '$compose_file' exec -T api python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=5)\"
"

cat <<'EOF'
Rollback deployment completed (no migrations were run).
If the database revision printed above is newer than the rollback image's head,
the schema is ahead of the code. That is safe only when every migration between
the two revisions is additive (check with `alembic history -r <head>:<current>`).
Never downgrade automatically; for data-dropping changes restore from backup.
EOF
