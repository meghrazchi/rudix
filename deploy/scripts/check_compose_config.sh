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
# The edge proxy mounts its Caddyfile and snippets from ./edge (R08-01).
mkdir -p "$tmp_dir/deploy/compose/edge"
cp "$repo_root"/deploy/compose/edge/* "$tmp_dir/deploy/compose/edge/"

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
MINIO_BUCKET=placeholder
NEO4J_USERNAME=placeholder
NEO4J_PASSWORD=placeholder
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
all_profiles="--profile graph --profile analytics --profile pooler --profile redis-split --profile mcp --profile backup"
# shellcheck disable=SC2086
check "staging (every profile)" -f deploy/compose/docker-compose.staging.yml $all_profiles
# shellcheck disable=SC2086
check "production (every profile)" -f deploy/compose/docker-compose.production.yml $all_profiles
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

# R08-01: with every profile active, only the edge publishes host ports, and only 80 and 443.
for env_name in staging production; do
  # shellcheck disable=SC2086
  if ! (cd "$tmp_dir" && docker compose -f "deploy/compose/docker-compose.$env_name.yml" \
    $all_profiles config --format json) > "$tmp_dir/$env_name.json"; then
    echo "FAILED  $env_name: docker compose config --format json" >&2
    failures=$((failures + 1))
    continue
  fi
  if python3 - "$tmp_dir/$env_name.json" <<'PY'
import json
import sys

services = json.load(open(sys.argv[1], encoding="utf-8"))["services"]
problems = []
for name, service in sorted(services.items()):
    for port in service.get("ports") or []:
        published = str(port.get("published", "")) if isinstance(port, dict) else str(port)
        if name != "edge" or published not in ("80", "443"):
            problems.append(f"{name} publishes {published or port}")
for problem in problems:
    print(f"  {problem}", file=sys.stderr)
sys.exit(1 if problems else 0)
PY
  then
    echo "ok      $env_name: only edge publishes ports (80, 443)"
  else
    echo "FAILED  $env_name: a service other than edge publishes a host port" >&2
    failures=$((failures + 1))
  fi
done

# R08-06: profile `backup` defines the one-shot dump and runner jobs; neither starts with a
# plain `up`, publishes a port, or restarts, and the runner reads its key from a read-only
# file mount, never from the environment.
for env_name in staging production; do
  default_services="$(cd "$tmp_dir" && docker compose -f "deploy/compose/docker-compose.$env_name.yml" config --services)"
  if printf '%s\n' "$default_services" | grep -q '^backup-'; then
    echo "FAILED  $env_name: backup services must be in the backup profile only" >&2
    failures=$((failures + 1))
  fi
  [ -f "$tmp_dir/$env_name.json" ] || continue
  if python3 - "$tmp_dir/$env_name.json" <<'PY'
import json
import sys

services = json.load(open(sys.argv[1], encoding="utf-8"))["services"]
problems = []
for name in ("backup-postgres-dump", "backup-runner"):
    service = services.get(name)
    if service is None:
        problems.append(f"{name} missing")
        continue
    if service.get("profiles") != ["backup"]:
        problems.append(f"{name} must have profiles [backup]")
    if service.get("restart") not in ("no", None):
        problems.append(f"{name} must not restart")
    work = [v for v in service.get("volumes", []) if v.get("target") == "/backup"]
    if not work or work[0].get("source") != "backup_work":
        problems.append(f"{name} must mount the backup_work volume at /backup")
dump = services.get("backup-postgres-dump", {})
if not str(dump.get("image", "")).startswith("postgres:16"):
    problems.append("backup-postgres-dump must default to the postgres:16 image")
if "pg_dump -Fc" not in " ".join(dump.get("command") or []):
    problems.append("backup-postgres-dump must run pg_dump -Fc")
runner = services.get("backup-runner", {})
environment = runner.get("environment") or {}
if environment.get("BACKUP_ENCRYPTION_KEY_FILE") != "/run/secrets/rudix-backup.key":
    problems.append("backup-runner must read BACKUP_ENCRYPTION_KEY_FILE from the key mount")
for name in ("QDRANT_URL", "MINIO_ENDPOINT", "DATABASE_URL", "ENVIRONMENT"):
    if name not in environment:
        problems.append(f"backup-runner must inherit the worker environment ({name})")
keys = [v for v in runner.get("volumes", []) if v.get("target") == "/run/secrets/rudix-backup.key"]
if not keys or keys[0].get("type") != "bind" or keys[0].get("read_only") is not True:
    problems.append("backup-runner key file must be a read-only bind mount")
elif (keys[0].get("bind") or {}).get("create_host_path", False) is not False:
    problems.append("backup-runner key mount must not create a missing host path")
if runner.get("entrypoint") != ["python", "scripts/backup_run.py"]:
    problems.append("backup-runner must run scripts/backup_run.py")
for problem in problems:
    print(f"  {problem}", file=sys.stderr)
sys.exit(1 if problems else 0)
PY
  then
    echo "ok      $env_name: backup profile (dump + runner, key file mount)"
  else
    echo "FAILED  $env_name: backup profile" >&2
    failures=$((failures + 1))
  fi
done

if [ "$failures" -ne 0 ]; then
  echo "$failures compose check(s) failed" >&2
  exit 1
fi
echo "All compose files parse."
