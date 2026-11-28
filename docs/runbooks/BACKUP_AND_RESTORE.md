# Backup and restore

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Active (0.8.0, R08-06); backups are off until an operator enables them, and no
  restore drill has been recorded
- `Last Updated`: 2026-11-28
- `Related Docs`: [README.md](./README.md), [RESTORE_DRILL_LOG.md](./RESTORE_DRILL_LOG.md),
  [../10_DEPLOYMENT_DOCKER.md](../10_DEPLOYMENT_DOCKER.md) "Backup strategy",
  [../11_SECURITY_AND_PRODUCTION_CHECKLIST.md](../11_SECURITY_AND_PRODUCTION_CHECKLIST.md)
  "Backups and restore", [../28_KUBERNETES_HELM_DEPLOYMENT.md](../28_KUBERNETES_HELM_DEPLOYMENT.md)
  "Data stores, backups, and restore"

## Backup kinds

| Kind | Produced by | Object in the backup bucket | Restore with |
|---|---|---|---|
| `postgres` | `pg_dump -Fc` (postgres:16 image) then `scripts/backup_run.py --kind postgres` | `<prefix>/postgres/<run>/postgres.dump.rbk` | `backup_restore.py --kind postgres`, then `pg_restore` |
| `qdrant` | `scripts/backup_run.py --kind qdrant` (one snapshot per deployment collection) | `<prefix>/qdrant/<run>/<collection>.snapshot.rbk` and `manifest.json.rbk` | `backup_restore.py --kind qdrant`, then snapshot upload |
| `objects` | `scripts/backup_run.py --kind objects` (incremental mirror of `MINIO_BUCKET`) | `<prefix>/objects/data/<sha256 of key>.rbk` and `<run>/manifest.json.rbk` | `backup_restore.py --kind objects`, then copy back |
| `neo4j` | not built (Community edition has no online dump); an operator backup may write a marker | operator-defined | rebuild the graph from documents |

Qdrant cluster caveat: a collection snapshot is taken by the node that answers
`QDRANT_URL`. In distributed mode Qdrant snapshots only the shards that node holds, so the
snapshot is complete only when that node has a replica of every shard (replication factor
equal to the node count). Otherwise rely on the rebuild path or snapshot each node; check the
Qdrant documentation for the deployed server version.

Each successful run writes `<prefix>/<kind>/latest.json`: `completed_at`, `object_key`,
`size_bytes`, `sha256` (of the ciphertext), `format_version`. A failed run leaves the previous
marker, so a stuck job shows up as a stale marker.

Every artifact is encrypted client-side (`RUDIXBK1`: AES-256-GCM, 4 MiB chunks, each bound
to the header, its index, and the final flag). Restore detects tampering, reordering,
truncation, and the wrong key, and writes nothing on failure.

Primary recovery paths come first: managed PostgreSQL point-in-time recovery
([DR_DATABASE_CORRUPTION.md](./DR_DATABASE_CORRUPTION.md)), provider replication and
versioning for managed object storage, and a vector index rebuild
([DR_VECTOR_INDEX_LOSS.md](./DR_VECTOR_INDEX_LOSS.md)). These backups are the
provider-independent copy.

## Detection

- `RudixBackupStale` (critical): `time() - max by (kind) (rudix_backup_last_success_timestamp_seconds) > 26 * 3600`
  for 15 minutes. A kind has not completed in 26 hours.
- `RudixBackupFreshnessUnknown` (warning): checks run but a marker is missing or unreadable,
  or the bucket cannot be read (`rudix_backup_freshness_checks_total{outcome=~"missing|error"}`).
- The release workflow's step "Check remote backup artifacts" fails (either gate mode).
- Logs: `backup.freshness.checked` with a non-`fresh` outcome, `backup.freshness.check_failed`,
  a CronJob `Failed` condition, or a non-zero exit of the host timer
  (`systemctl status rudix-backup.service`).

## Decision owner

- On-call engineer: investigates alerts and reruns jobs.
- Platform owner: bucket, credentials, key Secret, schedules, and switching the deploy gate.
- Incident commander: decides whether a restore runs against production and when.
- Security lead: approves every key rotation and every restore outside the production
  environment (drills included).

## Steps

### Set up (once per environment)

1. Platform owner creates the backup bucket in another account or region, with versioning, a
   retention policy (object lock where available), server-side encryption, access logging,
   and a noncurrent-version expiry that matches the retention policy.
2. Create credentials that can write and read the bucket (no delete where the provider
   allows it). Store them in the secret store as `BACKUP_S3_ACCESS_KEY` and
   `BACKUP_S3_SECRET_KEY`, or grant the workload a cloud identity instead.
3. Generate the key: `openssl rand -base64 32 > backup.key` on a trusted machine. Store it
   as a secret (Kubernetes: `kubectl create secret generic rudix-production-backup-key
   --from-file=backup.key=backup.key`; Compose: a file on the host, mode `0400`, owner uid
   `10001`, path in `BACKUP_ENCRYPTION_KEY_HOST_FILE`). Keep an offline copy with restricted
   access. Delete the working copy.
4. Configure: `BACKUP_ENABLED=true` (runner only; the chart sets it on the CronJobs),
   `BACKUP_BUCKET`, `BACKUP_PREFIX`, `BACKUP_S3_REGION`, `BACKUP_S3_ENDPOINT` (non-AWS),
   `BACKUP_S3_SSE` (`AES256` or `aws:kms` with `BACKUP_S3_KMS_KEY_ID`), and for the PostgreSQL
   dump a libpq `BACKUP_DATABASE_URL` of a read-only or maintenance role.
5. Schedule: chart `backup.enabled: true` (and `backup.postgres.enabled` if the logical dump is
   wanted besides PITR), or copy `deploy/scripts/run_compose_backup.sh` to the application
   directory and install the systemd timer or cron entry shown in the script.
6. Enable the freshness check everywhere beat runs: `BACKUP_FRESHNESS_CHECK_ENABLED=true`
   (with the same `BACKUP_BUCKET` and read credentials). Route the two alerts.
7. After every kind has a fresh marker, run a restore drill (below), then set the repository
   variable `DEPLOY_BACKUP_GATE=marker`.

### A backup alert fired

1. Find the kind in the alert labels and run the check by hand:
   `python scripts/check_backup_freshness.py` (inside the api container on Compose:
   `docker compose -f docker-compose.production.yml exec -T api python scripts/check_backup_freshness.py`).
   It prints `kind status age` only.
2. Look at the last run: `kubectl get jobs -l app.kubernetes.io/component=backup-<kind>` and
   `kubectl logs job/<name>`, or `journalctl -u rudix-backup.service`. The runner prints one
   line on failure with the error class (`backup <kind> failed: <Type>: <safe message>`).
3. Common causes: expired or rotated bucket credentials (`ClientError`), a missing or wrong
   key file (`BackupKeyError`), a full work volume, an unreachable Qdrant or MinIO, `pg_dump`
   version mismatch (must be 16 for a 16 server), or the timer not installed.
4. Fix the cause and rerun one kind: `kubectl create job --from=cronjob/rudix-backup-<kind>
   rudix-backup-<kind>-manual`, or `./run_compose_backup.sh production <kind>`.
5. If the freshness check itself fails (`outcome="error"`), check the read credentials and
   bucket name on the beat and api pods.

### Restore

1. Incident commander decides the target: a scratch store for inspection, or production.
2. Download and decrypt (the latest marker, or a specific run's object key):

   ```bash
   cd backend
   python scripts/backup_restore.py --kind postgres --latest --out /restore/postgres.dump
   python scripts/backup_restore.py --kind qdrant --latest --out /restore/qdrant
   python scripts/backup_restore.py --kind objects --latest --out /restore/objects
   # after a key rotation: add --key-file /keys/<old>.key for each older key
   ```

3. PostgreSQL: create an empty database, then
   `pg_restore --no-owner --no-privileges --exit-on-error --dbname "$RESTORE_DATABASE_URL" /restore/postgres.dump`.
   Re-run `deploy/sql/provision_roles.sql` grants if the roles differ. Verify with
   `python scripts/verify_postgres_restore.py --database-url "$RESTORE_DATABASE_URL"`.
4. Qdrant: upload each `<collection>.snapshot` to
   `POST /collections/<collection>/snapshots/upload?priority=snapshot`, then recreate the
   aliases in `aliases.json` (`restore_drill.sh` does both).
5. Objects: copy the restored tree back into the bucket (`mc mirror` or `aws s3 sync`), only
   after the incident commander confirms which objects are missing.
6. Remove `/restore` when done; it holds production data in plaintext.

### Restore drill

1. Prepare an empty scratch database and a scratch Qdrant with production access controls.
2. Optionally record row-count floors on the source first:
   `python scripts/verify_postgres_restore.py --database-url "$SOURCE_URL" --write-manifest floors.json`.
3. Run `RESTORE_DATABASE_URL=... RESTORE_QDRANT_URL=... RESTORE_MANIFEST=floors.json
   deploy/scripts/restore_drill.sh` (it refuses the live URLs; `RESTORE_DRILL_DRY_RUN=true`
   prints the plan). Point a temporary app stack at the scratch stores and set
   `RESTORE_API_URL` to also run the health and readiness smoke of the release workflow's
   "Integration smoke" job.
4. Copy the printed record into [RESTORE_DRILL_LOG.md](./RESTORE_DRILL_LOG.md), fill in the
   measured RPO and RTO, and drop the scratch stores.

### Rotate the backup key

1. Security lead approves. Generate a new key as in set-up step 3; create a new Secret
   version (or a new Secret name) and point `backup.encryptionKeySecret` or
   `BACKUP_ENCRYPTION_KEY_HOST_FILE` at it.
2. Keep every old key, offline and access-controlled, for as long as backups encrypted with it
   are retained (the bucket's retention policy). Record the switch date in the secret store so
   it is clear which key encrypted which runs; each file's header also carries a key id, which
   `backup_restore.py` uses to pick the matching `--key-file`.
3. The next `objects` run cannot read the previous manifest with the new key and copies every
   object again (logged as `backup.objects.previous_manifest_unreadable`); expect a larger run.
4. Run one backup of each kind and a restore with only the new key, then a restore of an
   older backup with `--key-file <old key>`.
5. On suspected key exposure, follow [DR_CREDENTIAL_COMPROMISE.md](./DR_CREDENTIAL_COMPROMISE.md):
   rotate, then decide with the security lead whether backups made with the old key must be
   re-created and the old ones deleted.

## Verification

- `python scripts/check_backup_freshness.py` exits 0 and lists every configured kind as
  `fresh`; `rudix_backup_last_success_timestamp_seconds` moves forward after each run.
- `verify_postgres_restore.py` exits 0 on the restored database.
- The restored Qdrant answers a search and `GET /collections` lists every collection in the
  manifest; the aliases point at the same collections as in `aliases.json`.
- The drill is recorded in [RESTORE_DRILL_LOG.md](./RESTORE_DRILL_LOG.md) and the scratch
  data is gone.
