# DR: database corruption

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Active (0.8.0, R08-13); not yet exercised in a drill
- `Last Updated`: 2026-11-28
- `Related Docs`: [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md),
  [RESTORE_DRILL_LOG.md](./RESTORE_DRILL_LOG.md),
  [../06_DATABASE_SCHEMA.md](../06_DATABASE_SCHEMA.md),
  [../11_SECURITY_AND_PRODUCTION_CHECKLIST.md](../11_SECURITY_AND_PRODUCTION_CHECKLIST.md)

Scope: PostgreSQL holds wrong or missing data (a bad migration, an operator `DELETE`, an
application bug that overwrote rows), or the database cannot be read (storage corruption,
`could not read block`, index corruption). Managed PostgreSQL point-in-time recovery (PITR) is
the first choice; the encrypted `pg_dump` backup is the fallback.

## Detection

- API 5xx rate (`RudixApiHighErrorRate`) with database errors in logs
  (`sqlalchemy.exc.*`, `asyncpg.exceptions.DataCorruptedError`, `could not read block`,
  `invalid page in block`).
- `/api/v1/ready` reports `postgres` down while the server is up.
- Users or admins report missing documents, chats, or members; audit logs show an unexpected
  bulk change; a migration failed half-way (`alembic current` differs from the expected head).
- The managed provider reports storage or replication errors.

## Decision owner

- Incident commander: decides whether to restore, chooses the restore point, and approves
  the switch of `DATABASE_URL`. Restoring discards every write after the restore point.
- On-call engineer: runs the restore and verification.
- Platform owner: managed database console and roles.
- Data protection lead: informed when customer data is lost or exposed; decides on notices.
- Security lead: involved when the cause may be malicious (then also follow
  [DR_CREDENTIAL_COMPROMISE.md](./DR_CREDENTIAL_COMPROMISE.md)).

## Steps

1. Contain: stop the writers so the damage does not grow. Scale workers and beat to 0
   (`kubectl scale deploy -l app.kubernetes.io/component=beat --replicas=0`, then the worker
   pools; Compose: `docker compose stop beat worker-ingest worker-graph worker-sync worker-eval worker-default`).
   Put the API in maintenance at the edge or scale it to 0 if writes continue to corrupt data.
2. Find the last good moment: from audit logs, the failed migration's start time, or the first
   error in logs. Write the chosen restore point (UTC) in the incident record.
3. Path A, managed PITR (first choice):
   1. In the provider console or CLI, restore the instance to the chosen time as a NEW
      instance. Never restore over the live instance.
   2. Recreate the roles if the provider does not copy them: run
      `deploy/sql/provision_roles.sql` as the schema owner (`rudix_app`, `rudix_maintenance`),
      then set their passwords from the secret store.
   3. Verify the new instance (step 5) before switching.
4. Path B, logical restore from the backup bucket (when PITR is unavailable or does not reach
   back far enough):
   1. Create an empty database on a healthy server.
   2. `python scripts/backup_restore.py --kind postgres --latest --out /restore/postgres.dump`
      (or `--object-key` of an older run; list runs under `<prefix>/postgres/` in the bucket).
   3. `pg_restore --no-owner --no-privileges --exit-on-error --dbname "$RESTORE_DATABASE_URL" /restore/postgres.dump`,
      connected as the role that should own the schema (the migration owner), so the
      restored objects belong to it.
   4. Re-apply grants with `deploy/sql/provision_roles.sql`. The dump's point in time is its
      marker's `completed_at`; everything after it is lost unless recovered from the damaged
      database.
5. Verify the restored database before any switch:

   ```bash
   python scripts/verify_postgres_restore.py --database-url "$RESTORE_DATABASE_URL" \
       [--manifest floors.json] [--expect-revision <head>]
   ```

   It checks `alembic_version`, the required tables, RLS on every policy table, primary keys,
   key indexes, and row-count floors, and exits 1 on any failure. If the revision is behind
   the release, run `alembic upgrade head` against the restored database with the migration
   role.
6. Switch: point `DATABASE_URL`, `DATABASE_MIGRATION_URL`, `DATABASE_MAINTENANCE_URL` (and
   the read replica URL, once the replica is recreated, when replica routing is in use) at
   the restored instance; redeploy or
   restart the API, workers, and beat. Keep the damaged instance read-only for investigation;
   delete it only after the incident commander closes the incident.
7. Reconcile the other stores with the restored rows:
   - Qdrant may hold points for documents that the restore removed, or lack points for
     documents re-created after the restore point: run
     `python scripts/vector_index.py status`, then reindex affected documents (or rebuild,
     [DR_VECTOR_INDEX_LOSS.md](./DR_VECTOR_INDEX_LOSS.md)). Retrieval always filters by
     organisation and by document rows, so orphan points are not served.
   - Object storage may hold objects with no document row (uploads after the restore point);
     they are unreachable through the API. List and remove them later through the data
     deletion process (docs/11 "Data deletion"); never delete them during the incident.
   - Pending `outbox_messages` rows from before the restore point are published again by the
     relay; that is safe (tasks are idempotent).
8. Restart workers and beat; then check the document reaper picks up documents stuck in
   `processing` (docs/27 "Resume and reaper").
9. Record the restore point, data loss window, and timings in
   [RESTORE_DRILL_LOG.md](./RESTORE_DRILL_LOG.md).

## Verification

- `verify_postgres_restore.py` exits 0 on the database the application now uses.
- `/api/v1/ready` reports `postgres` up; the API 5xx alert clears.
- Spot-check with an admin account: organisations, members, documents, and recent chats
  exist up to the restore point; RLS still isolates tenants (an admin of one organisation
  sees none of another's documents).
- No new database errors in logs for one hour; the next `postgres` backup run succeeds and
  its marker is fresh.
