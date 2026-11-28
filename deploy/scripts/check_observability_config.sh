#!/bin/sh
# Validates the observability Compose stack (R08-09, B2) with `docker compose config -q`.
#
# Checks, on a copy of infra/observability in a temporary directory with placeholder env
# files (real env files and secrets are never read):
#   - the development stack (infra/observability/docker-compose.yml) alone;
#   - the deploy overlay (docker-compose.deploy.yml) on top of it;
#   - the deploy overlay refuses to render without GRAFANA_ADMIN_PASSWORD (no default);
#   - with the overlay only Grafana publishes a port, and only on 127.0.0.1.
# No container is started. Exits non-zero when any check fails.
#
#   deploy/scripts/check_observability_config.sh
set -eu

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

cp -R "$repo_root/infra/observability" "$tmp_dir/observability"
rm -rf "$tmp_dir/observability/secrets"
mkdir -p "$tmp_dir/observability/secrets"
# Placeholder secret files with the names the deploy configs read.
for name in metrics_token oncall_pager_url oncall_ticket_url; do
  printf 'placeholder\n' > "$tmp_dir/observability/secrets/$name"
done

cat > "$tmp_dir/deploy.env" <<'EOF'
GRAFANA_ADMIN_PASSWORD=placeholder
POSTGRES_EXPORTER_USER=placeholder
POSTGRES_EXPORTER_PASSWORD=placeholder
POSTGRES_EXPORTER_SSLMODE=require
POSTGRES_DB=placeholder
REDIS_PASSWORD=placeholder
EOF
grep -v '^GRAFANA_ADMIN_PASSWORD=' "$tmp_dir/deploy.env" > "$tmp_dir/no-grafana-password.env"
: > "$tmp_dir/empty.env"

failures=0
dev="-f observability/docker-compose.yml"
deploy="$dev -f observability/docker-compose.deploy.yml"

# Variables from the caller's shell would hide a missing default; clear the ones we check.
unset GRAFANA_ADMIN_PASSWORD POSTGRES_EXPORTER_USER POSTGRES_EXPORTER_PASSWORD \
  POSTGRES_EXPORTER_SSLMODE POSTGRES_DB REDIS_PASSWORD 2>/dev/null || true

check() {
  label="$1"
  shift
  # shellcheck disable=SC2086 # the file list is intentionally split
  if (cd "$tmp_dir" && docker compose "$@" config -q); then
    echo "ok      $label"
  else
    echo "FAILED  $label" >&2
    failures=$((failures + 1))
  fi
}

# shellcheck disable=SC2086
check "observability (dev)" --env-file empty.env $dev
# shellcheck disable=SC2086
check "observability + deploy overlay" --env-file deploy.env $deploy

# shellcheck disable=SC2086
if (cd "$tmp_dir" && docker compose --env-file no-grafana-password.env $deploy config -q) \
  >/dev/null 2>&1; then
  echo "FAILED  deploy overlay renders without GRAFANA_ADMIN_PASSWORD" >&2
  failures=$((failures + 1))
else
  echo "ok      deploy overlay requires GRAFANA_ADMIN_PASSWORD"
fi

# shellcheck disable=SC2086
if (cd "$tmp_dir" && docker compose --env-file deploy.env $deploy config --format json) \
  > "$tmp_dir/deploy.json"; then
  if python3 - "$tmp_dir/deploy.json" <<'EOF'
import json
import sys

services = json.load(open(sys.argv[1]))["services"]
problems = []
for name, service in sorted(services.items()):
    for port in service.get("ports") or []:
        if name != "grafana" or port.get("host_ip") != "127.0.0.1":
            problems.append(f"{name} publishes {port}")
grafana = services["grafana"]["environment"]
if grafana.get("GF_AUTH_ANONYMOUS_ENABLED") != "false":
    problems.append("grafana anonymous access is not disabled")
if "--web.enable-lifecycle" in services["prometheus"].get("command", []):
    problems.append("prometheus lifecycle API is enabled")
for name, target in (("prometheus", "/etc/prometheus/secrets"), ("alertmanager", "/etc/alertmanager/secrets")):
    if not any(v.get("target") == target for v in services[name].get("volumes") or []):
        problems.append(f"{name} does not mount {target}")
for problem in problems:
    print(f"FAILED  deploy overlay: {problem}", file=sys.stderr)
sys.exit(1 if problems else 0)
EOF
  then
    echo "ok      deploy overlay publishes only Grafana on 127.0.0.1"
  else
    failures=$((failures + 1))
  fi
else
  echo "FAILED  deploy overlay JSON render" >&2
  failures=$((failures + 1))
fi

if [ "$failures" -ne 0 ]; then
  echo "check_observability_config: $failures check(s) failed" >&2
  exit 1
fi
echo "check_observability_config: all checks passed"
