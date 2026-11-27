#!/usr/bin/env bash
# Local development: infrastructure in Docker, app processes on the host.
#
#   Docker: postgres redis rabbitmq qdrant minio (+ bucket init) clamav [matomo]
#   Host:   API (uvicorn --reload), Celery worker, Celery beat, Next.js dev server
#
# Usage: make dev            (or: scripts/dev-local.sh)
# Env:   DEV_SKIP_MATOMO=1   skip the Matomo analytics containers
#        ENTERPRISE_GRAPH_ENABLED=true (shell or .env) also starts Neo4j
#        DEV_SKIP_MIGRATE=1  skip `alembic upgrade head`
#        DEV_SKIP_FRONTEND=1 run only the backend processes
#
# Ctrl+C stops the host processes. Containers keep running; stop them with
# `make dev-down` (or `docker compose stop`).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

INFRA_SERVICES=(postgres redis rabbitmq qdrant minio clamav)
if [[ "${DEV_SKIP_MATOMO:-0}" != "1" ]]; then
  INFRA_SERVICES+=(matomo-db matomo)
fi

# Neo4j lives behind the enterprise-graph compose profile; start it when the
# API will expect it (shell env wins over .env, matching the backend settings).
graph_enabled="${ENTERPRISE_GRAPH_ENABLED:-}"
if [[ -z "$graph_enabled" && -f .env ]]; then
  graph_enabled="$(grep -E '^ENTERPRISE_GRAPH_ENABLED=' .env | tail -n 1 | cut -d= -f2- | tr -d '"' || true)"
fi
COMPOSE_ARGS=()
if [[ "$(echo "$graph_enabled" | tr '[:upper:]' '[:lower:]')" == "true" ]]; then
  COMPOSE_ARGS=(--profile enterprise-graph)
  INFRA_SERVICES+=(neo4j)
fi

log() { printf '\033[1;34m[dev]\033[0m %s\n' "$*"; }

# The containerized app services would compete for port 8000 and the queue.
running_app_services="$(docker compose ps --status running --services 2>/dev/null \
  | grep -xE 'api|worker|beat' || true)"
if [[ -n "$running_app_services" ]]; then
  log "Stopping containerized app services: $(echo "$running_app_services" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  docker compose stop $running_app_services
fi

# Preflight: fail early, with a clear owner, when a host port the stack needs
# is already taken by another project's container or a local process.
PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "$ROOT_DIR")}"
PORT_CHECKS=(postgres:5432 redis:6379 rabbitmq:5672 rabbitmq:15672 qdrant:6333 qdrant:6334
  minio:9000 minio:9001 clamav:3310 host-api:8000)
if [[ "${DEV_SKIP_MATOMO:-0}" != "1" ]]; then PORT_CHECKS+=(matomo:8081); fi
if [[ "${DEV_SKIP_FRONTEND:-0}" != "1" ]]; then PORT_CHECKS+=(host-web:3000); fi
if ((${#COMPOSE_ARGS[@]} > 0)); then PORT_CHECKS+=(neo4j:7474 neo4j:7687); fi

conflicts=()
for check in "${PORT_CHECKS[@]}"; do
  service="${check%%:*}" port="${check##*:}"
  # `publish=` also matches ports inside published ranges (e.g. 6333-6334).
  owner="$(docker ps --filter "publish=${port}" --format \
    '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.service"}}' \
    | head -n 1 || true)"
  if [[ -n "$owner" ]]; then
    IFS='|' read -r name project owner_service <<<"$owner"
    if [[ "$project" == "$PROJECT" && "$owner_service" == "$service" ]]; then
      continue # our own container, already running
    fi
    conflicts+=("port ${port} (${service}) is used by container '${name}' -> docker stop ${name}")
  elif lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    process="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN | awk 'NR==2 {print $1" (pid "$2")"}')"
    conflicts+=("port ${port} (${service#host-}) is used by ${process}")
  fi
done
# Next.js refuses a second `next dev` in the same project directory.
if [[ "${DEV_SKIP_FRONTEND:-0}" != "1" ]]; then
  for pid in $(pgrep -f 'next-server|next dev' || true); do
    cwd="$(lsof -a -d cwd -p "$pid" -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1)"
    if [[ "$cwd" == "$ROOT_DIR/frontend" ]]; then
      conflicts+=("next dev already runs in frontend/ (pid ${pid}) -> kill ${pid} or DEV_SKIP_FRONTEND=1")
      break
    fi
  done
fi

if ((${#conflicts[@]} > 0)); then
  log "Cannot start: resolve these conflicts first"
  for conflict in "${conflicts[@]}"; do printf '  - %s\n' "$conflict"; done
  exit 1
fi

log "Starting infrastructure: ${INFRA_SERVICES[*]}"
docker compose ${COMPOSE_ARGS[@]+"${COMPOSE_ARGS[@]}"} up -d --wait "${INFRA_SERVICES[@]}"
# One-shot bucket setup; runs to completion (idempotent).
docker compose up --no-log-prefix minio-init >/dev/null

if [[ ! -x backend/.venv/bin/python ]]; then
  log "Backend virtualenv missing; running make -C backend install"
  make -C backend install
fi

if [[ "${DEV_SKIP_FRONTEND:-0}" != "1" && ! -d frontend/node_modules ]]; then
  log "frontend/node_modules missing; running npm install"
  npm --prefix frontend install
fi

if [[ "${DEV_SKIP_MIGRATE:-0}" != "1" ]]; then
  log "Applying database migrations"
  make -C backend migrate
fi

pids=()
# Job control: every background job gets its own process group, so cleanup
# can stop make *and* the uvicorn/celery/next processes it spawned.
set -m

# Run a command in the background with a colored, labelled output prefix.
run() {
  local name="$1" color="$2"
  shift 2
  (
    "$@" 2>&1 | while IFS= read -r line; do
      printf '\033[%sm%-8s\033[0m| %s\n' "$color" "$name" "$line"
    done
  ) &
  pids+=("$!")
}

cleanup() {
  trap - INT TERM EXIT
  log "Stopping host processes..."
  # Silence bash's "Terminated" job notices; our own messages go to stdout.
  exec 2>/dev/null
  for pid in ${pids[@]+"${pids[@]}"}; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  sleep 2
  for pid in ${pids[@]+"${pids[@]}"}; do
    kill -KILL -- "-$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  log "Stopped. Containers are still running (make dev-down to stop them)."
}
trap cleanup INT TERM EXIT

run api "1;32" make -C backend run-api
run worker "1;33" make -C backend run-worker
run beat "1;35" make -C backend run-beat
if [[ "${DEV_SKIP_FRONTEND:-0}" != "1" ]]; then
  run web "1;36" npm --prefix frontend run dev
fi

log "API http://localhost:8000  |  Web http://localhost:3000  |  Ctrl+C to stop"
wait
