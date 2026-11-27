#!/bin/sh
# Validates every compose file with `docker compose config -q` (R06-04).
#
# Staging and production need RUDIX_*_IMAGE values and deploy/compose/.env, the dev file
# needs the repository .env, and integration needs .env.ci.integration; none of those is
# committed. Each check therefore runs on a copy of the compose files in a temporary
# directory that mirrors the repository layout, with placeholder env files and image
# values. Real env files are never read. Exits non-zero when any configuration fails.
#
#   deploy/scripts/check_compose_config.sh
set -eu

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/deploy/compose" "$tmp_dir/infra/rabbitmq" "$tmp_dir/backend" "$tmp_dir/ci/stubs"
cp "$repo_root/docker-compose.yml" "$tmp_dir/docker-compose.yml"
cp "$repo_root"/deploy/compose/docker-compose.*.yml "$tmp_dir/deploy/compose/"
cp "$repo_root"/infra/rabbitmq/* "$tmp_dir/infra/rabbitmq/"
# Staging and production mount the RabbitMQ files from ./rabbitmq next to the compose file
# (deploy_compose_remote.sh copies them there).
mkdir -p "$tmp_dir/deploy/compose/rabbitmq"
cp "$repo_root"/infra/rabbitmq/* "$tmp_dir/deploy/compose/rabbitmq/"

placeholder_env() {
  cat <<'EOF'
RUDIX_API_IMAGE=registry.invalid/rudix/api:check
RUDIX_WORKER_IMAGE=registry.invalid/rudix/worker:check
RUDIX_FRONTEND_IMAGE=registry.invalid/rudix/frontend:check
POSTGRES_USER=placeholder
POSTGRES_PASSWORD=placeholder
POSTGRES_DB=placeholder
RABBITMQ_DEFAULT_USER=placeholder
RABBITMQ_DEFAULT_PASS=placeholder
REDIS_PASSWORD=placeholder
MINIO_ROOT_USER=placeholder
MINIO_ROOT_PASSWORD=placeholder
EOF
}

placeholder_env > "$tmp_dir/.env"
placeholder_env > "$tmp_dir/deploy/compose/.env"
placeholder_env > "$tmp_dir/.env.ci.integration"

export RUDIX_API_IMAGE=registry.invalid/rudix/api:check
export RUDIX_WORKER_IMAGE=registry.invalid/rudix/worker:check
export RUDIX_FRONTEND_IMAGE=registry.invalid/rudix/frontend:check

failures=0

check() {
  label="$1"
  shift
  if (cd "$tmp_dir" && docker compose "$@" config -q); then
    echo "ok      $label"
  else
    echo "FAILED  $label" >&2
    failures=$((failures + 1))
  fi
}

check "docker-compose.yml" -f docker-compose.yml
check "docker-compose.yml --profile pools" -f docker-compose.yml --profile pools
check "staging" -f deploy/compose/docker-compose.staging.yml
check "production" -f deploy/compose/docker-compose.production.yml
check "integration" -f deploy/compose/docker-compose.integration.yml
check "integration + stub" \
  -f deploy/compose/docker-compose.integration.yml \
  -f deploy/compose/docker-compose.integration-stub.yml

# Staging and production run five pools and exactly one beat; no single `worker` remains.
for env_name in staging production; do
  services="$(cd "$tmp_dir" && docker compose -f "deploy/compose/docker-compose.$env_name.yml" config --services)"
  for pool in ingest graph sync eval default; do
    if ! printf '%s\n' "$services" | grep -qx "worker-$pool"; then
      echo "FAILED  $env_name: missing service worker-$pool" >&2
      failures=$((failures + 1))
    fi
  done
  if printf '%s\n' "$services" | grep -qx "worker"; then
    echo "FAILED  $env_name: the single 'worker' service must be replaced by the pools" >&2
    failures=$((failures + 1))
  fi
  if [ "$(printf '%s\n' "$services" | grep -cx "beat")" -ne 1 ]; then
    echo "FAILED  $env_name: expected exactly one beat service" >&2
    failures=$((failures + 1))
  fi
done

if [ "$failures" -ne 0 ]; then
  echo "$failures compose check(s) failed" >&2
  exit 1
fi
echo "All compose files parse."
