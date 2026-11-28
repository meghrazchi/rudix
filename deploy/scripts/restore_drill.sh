#!/bin/sh
# Restore drill (R08-06, R08-04): restore the latest encrypted backups into SCRATCH data
# stores, verify them, and print a drill record template. Runbook:
# docs/runbooks/BACKUP_AND_RESTORE.md; record results in docs/runbooks/RESTORE_DRILL_LOG.md.
#
# Run from the repository root on an operator machine or a one-off pod that has the backend
# virtualenv (or the worker image), pg_restore 16, curl, and network access to the backup
# bucket and the scratch stores. It never touches the live stores: it refuses to run when
# RESTORE_DATABASE_URL names the same server and database as DATABASE_URL,
# DATABASE_MIGRATION_URL, or DATABASE_MAINTENANCE_URL (whatever the role, password, or
# options), or RESTORE_QDRANT_URL equals QDRANT_URL.
#
# Required:
#   RESTORE_DATABASE_URL   postgresql:// URL of an EMPTY scratch database. Prefer a URL
#                          without a password plus PGPASSFILE: the URL is passed to
#                          pg_restore on its command line.
#   BACKUP_BUCKET, BACKUP_ENCRYPTION_KEY_FILE, BACKUP_S3_* (read by backup_restore.py)
# Optional:
#   RESTORE_QDRANT_URL      scratch Qdrant (required unless RESTORE_SKIP_QDRANT=true)
#   RESTORE_QDRANT_API_KEY  api key of the scratch Qdrant
#   RESTORE_SKIP_QDRANT     true: restore and verify PostgreSQL only
#   RESTORE_MANIFEST        row_count_floors JSON (verify_postgres_restore.py --manifest)
#   RESTORE_EXPECT_REVISION alembic revision expected (default: the shipped head)
#   RESTORE_KEY_FILES       space-separated older backup keys (after a rotation)
#   RESTORE_API_URL         base URL of an app stack pointed at the scratch stores; runs the
#                           health and readiness checks of the release workflow's
#                           "Integration smoke" job (.github/workflows/release.yml)
#   RESTORE_WORK_DIR        working directory (default: a new temp dir, removed at the end)
#   RESTORE_KEEP_FILES      true: keep the decrypted files (they hold production data)
#   PYTHON                  interpreter (default backend/.venv/bin/python, else python3)
#   RESTORE_DRILL_DRY_RUN   true: check the inputs and print the plan, restore nothing
#
# Restored data is production data: restore only into stores with the same access controls
# as production, mask or drop it after the drill (docs/11 "Backups and restore").
set -eu

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
backend_dir="$repo_root/backend"

if [ -z "${RESTORE_DATABASE_URL:-}" ]; then
  echo "Missing required variable: RESTORE_DATABASE_URL" >&2
  exit 1
fi

# libpq form of a SQLAlchemy URL (pg_restore and psql do not take +asyncpg).
libpq_url() {
  printf '%s' "$1" | sed -e 's#^postgresql+asyncpg://#postgresql://#' \
    -e 's#^postgres+asyncpg://#postgresql://#' -e 's#^postgres://#postgresql://#'
}

# Server and database a URL names, without credentials or options: the live database is
# refused whichever role, password, or connection options the scratch URL uses.
database_identity() {
  libpq_url "$1" | sed -e 's#^\(postgresql://\)[^@/]*@#\1#' -e 's#[?].*$##' -e 's#/*$##' \
    -e 's#^\(postgresql://[^/:]*\)/#\1:5432/#' -e 's#^\(postgresql://[^/:]*\)$#\1:5432#' |
    tr '[:upper:]' '[:lower:]'
}

restore_db_url="$(libpq_url "$RESTORE_DATABASE_URL")"
restore_db="$(database_identity "$RESTORE_DATABASE_URL")"
for live_var in DATABASE_URL DATABASE_MIGRATION_URL DATABASE_MAINTENANCE_URL; do
  eval "live_value=\${$live_var:-}"
  if [ -n "$live_value" ] && [ "$(database_identity "$live_value")" = "$restore_db" ]; then
    echo "Refusing: RESTORE_DATABASE_URL equals $live_var (restore only into a scratch database)" >&2
    exit 2
  fi
done

skip_qdrant="${RESTORE_SKIP_QDRANT:-false}"
if [ "$skip_qdrant" != "true" ]; then
  if [ -z "${RESTORE_QDRANT_URL:-}" ]; then
    echo "Missing RESTORE_QDRANT_URL (or set RESTORE_SKIP_QDRANT=true)" >&2
    exit 1
  fi
  if [ -n "${QDRANT_URL:-}" ] && [ "${QDRANT_URL%/}" = "${RESTORE_QDRANT_URL%/}" ]; then
    echo "Refusing: RESTORE_QDRANT_URL equals QDRANT_URL (restore only into a scratch Qdrant)" >&2
    exit 2
  fi
fi

if [ -n "${PYTHON:-}" ]; then
  python_bin="$PYTHON"
elif [ -x "$backend_dir/.venv/bin/python" ]; then
  python_bin="$backend_dir/.venv/bin/python"
else
  python_bin="python3"
fi

key_args=""
for key_file in ${RESTORE_KEY_FILES:-}; do
  key_args="$key_args --key-file $key_file"
done
verify_args=""
if [ -n "${RESTORE_MANIFEST:-}" ]; then
  verify_args="$verify_args --manifest $RESTORE_MANIFEST"
fi
if [ -n "${RESTORE_EXPECT_REVISION:-}" ]; then
  verify_args="$verify_args --expect-revision $RESTORE_EXPECT_REVISION"
fi

if [ "${RESTORE_DRILL_DRY_RUN:-false}" = "true" ]; then
  echo "plan: download and decrypt the latest postgres backup (backup_restore.py)"
  echo "plan: pg_restore --no-owner --no-privileges into the scratch database"
  echo "plan: verify_postgres_restore.py${verify_args}"
  if [ "$skip_qdrant" != "true" ]; then
    echo "plan: download the latest qdrant snapshots and upload them to the scratch Qdrant"
  fi
  if [ -n "${RESTORE_API_URL:-}" ]; then
    echo "plan: smoke /api/v1/health and /api/v1/ready on RESTORE_API_URL"
  fi
  exit 0
fi

work_dir="${RESTORE_WORK_DIR:-}"
created_work_dir=false
if [ -z "$work_dir" ]; then
  work_dir="$(mktemp -d)"
  created_work_dir=true
fi
chmod 700 "$work_dir"
cleanup() {
  if [ "${RESTORE_KEEP_FILES:-false}" != "true" ]; then
    rm -rf "$work_dir/postgres.dump" "$work_dir/qdrant"
    if [ "$created_work_dir" = "true" ]; then
      rm -rf "$work_dir"
    fi
  fi
}
trap cleanup EXIT

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

drill_started="$(now)"
echo "== postgres: download and decrypt ($(now))"
# shellcheck disable=SC2086
(cd "$backend_dir" && "$python_bin" scripts/backup_restore.py --kind postgres --latest \
  --out "$work_dir/postgres.dump" $key_args)

echo "== postgres: pg_restore into the scratch database ($(now))"
pg_restore --no-owner --no-privileges --exit-on-error --dbname "$restore_db_url" \
  "$work_dir/postgres.dump"
postgres_restored="$(now)"

echo "== postgres: verify ($(now))"
# shellcheck disable=SC2086
(cd "$backend_dir" && "$python_bin" scripts/verify_postgres_restore.py \
  --database-url "$restore_db_url" $verify_args)

qdrant_restored="skipped"
if [ "$skip_qdrant" != "true" ]; then
  echo "== qdrant: download and decrypt snapshots ($(now))"
  # shellcheck disable=SC2086
  (cd "$backend_dir" && "$python_bin" scripts/backup_restore.py --kind qdrant --latest \
    --out "$work_dir/qdrant" $key_args)
  for snapshot in "$work_dir"/qdrant/*.snapshot; do
    [ -f "$snapshot" ] || continue
    collection="$(basename "$snapshot" .snapshot)"
    echo "== qdrant: upload $collection"
    if [ -n "${RESTORE_QDRANT_API_KEY:-}" ]; then
      curl -fsS -X POST -H "api-key: $RESTORE_QDRANT_API_KEY" \
        -F "snapshot=@$snapshot" \
        "${RESTORE_QDRANT_URL%/}/collections/$collection/snapshots/upload?priority=snapshot" >/dev/null
    else
      curl -fsS -X POST -F "snapshot=@$snapshot" \
        "${RESTORE_QDRANT_URL%/}/collections/$collection/snapshots/upload?priority=snapshot" >/dev/null
    fi
  done
  alias_actions="$("$python_bin" -c 'import json,sys; print(json.dumps({"actions": [{"create_alias": {"alias_name": a["alias"], "collection_name": a["collection"]}} for a in json.load(open(sys.argv[1]))]}))' "$work_dir/qdrant/aliases.json")"
  if [ "$alias_actions" != '{"actions": []}' ]; then
    echo "== qdrant: recreate aliases"
    if [ -n "${RESTORE_QDRANT_API_KEY:-}" ]; then
      curl -fsS -X POST -H "api-key: $RESTORE_QDRANT_API_KEY" -H "Content-Type: application/json" \
        --data "$alias_actions" "${RESTORE_QDRANT_URL%/}/collections/aliases" >/dev/null
    else
      curl -fsS -X POST -H "Content-Type: application/json" \
        --data "$alias_actions" "${RESTORE_QDRANT_URL%/}/collections/aliases" >/dev/null
    fi
  fi
  qdrant_restored="$(now)"
fi

smoke_result="not run (RESTORE_API_URL unset)"
if [ -n "${RESTORE_API_URL:-}" ]; then
  echo "== smoke: health and readiness ($(now))"
  curl -fsS "${RESTORE_API_URL%/}/api/v1/health" >/dev/null
  curl -fsS "${RESTORE_API_URL%/}/api/v1/ready" >/dev/null
  smoke_result="passed"
fi
drill_finished="$(now)"

cat <<EOF

== Drill record (copy into docs/runbooks/RESTORE_DRILL_LOG.md and complete it)
| Field | Value |
|---|---|
| Date (UTC) | ${drill_started%%T*} |
| Environment | <staging or production backups> |
| Run by (role) | <role, never a name> |
| Backup marker completed_at (postgres / qdrant) | <from the markers> |
| Drill started | ${drill_started} |
| PostgreSQL restored | ${postgres_restored} |
| Qdrant restored | ${qdrant_restored} |
| verify_postgres_restore.py | passed |
| Smoke | ${smoke_result} |
| Drill finished | ${drill_finished} |
| RPO (incident time minus marker completed_at) | <measured> |
| RTO (drill finished minus drill started, plus provisioning) | <measured> |
| Issues and follow-ups | <none or links> |
EOF
