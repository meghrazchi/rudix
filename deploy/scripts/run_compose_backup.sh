#!/bin/sh
# Run the Compose backup jobs (profile `backup`, R08-06) on the deploy host.
#
#   deploy/scripts/run_compose_backup.sh <staging|production> <postgres|qdrant|objects|all>
#
# Run from the application directory on the host (DEPLOY_APP_PATH: the compose file and
# .env), or set RUDIX_COMPOSE_DIR. Meant for a host cron entry or systemd timer; there is no
# scheduler container. Example systemd units (daily at 02:30 UTC, all kinds):
#
#   # /etc/systemd/system/rudix-backup.service
#   [Service]
#   Type=oneshot
#   WorkingDirectory=/srv/rudix
#   ExecStart=/srv/rudix/run_compose_backup.sh production all
#
#   # /etc/systemd/system/rudix-backup.timer
#   [Timer]
#   OnCalendar=*-*-* 02:30:00 UTC
#   Persistent=true
#   [Install]
#   WantedBy=timers.target
#
# or cron: `30 2 * * * cd /srv/rudix && ./run_compose_backup.sh production all`.
#
# Needs in .env: BACKUP_ENABLED=true, BACKUP_BUCKET, BACKUP_S3_* (or an instance role), and
# BACKUP_ENCRYPTION_KEY_HOST_FILE pointing at the key file on the host (mode 0400, owned by
# uid 10001). Exits non-zero when any kind fails, so the timer reports the failure; the
# freshness alert (rules/backups.yml) catches a timer that stopped running.
set -eu

environment_name="${1:-}"
kind="${2:-}"
case "$environment_name" in
  staging | production) ;;
  *)
    echo "Usage: $0 <staging|production> <postgres|qdrant|objects|all>" >&2
    exit 1
    ;;
esac
case "$kind" in
  postgres | qdrant | objects) kinds="$kind" ;;
  all) kinds="postgres qdrant objects" ;;
  *)
    echo "Usage: $0 <staging|production> <postgres|qdrant|objects|all>" >&2
    exit 1
    ;;
esac

cd "${RUDIX_COMPOSE_DIR:-.}"
compose_file="docker-compose.${environment_name}.yml"
if [ ! -f "$compose_file" ]; then
  echo "Compose file not found: $compose_file (run from the application directory)" >&2
  exit 1
fi

compose() {
  docker compose -f "$compose_file" --profile backup "$@"
}

# The shared work volume belongs to the runner's user (10001); only this directory, never
# the key file, is changed.
compose run --rm --no-deps --entrypoint sh backup-postgres-dump \
  -c 'chown 10001:10001 /backup && chmod 700 /backup'

failed=""
for item in $kinds; do
  echo "backup $item: started $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  if [ "$item" = "postgres" ]; then
    if ! compose run --rm --no-deps backup-postgres-dump; then
      echo "backup postgres: pg_dump failed" >&2
      failed="$failed postgres"
      continue
    fi
  fi
  if compose run --rm --no-deps backup-runner --kind "$item"; then
    echo "backup $item: finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  else
    echo "backup $item: failed" >&2
    failed="$failed $item"
  fi
done

if [ -n "$failed" ]; then
  echo "backup failed for:$failed" >&2
  exit 1
fi
