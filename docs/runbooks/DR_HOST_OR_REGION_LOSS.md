# DR: host or region loss

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Active (0.8.0, R08-13); not yet exercised in a drill
- `Last Updated`: 2026-11-28
- `Related Docs`: [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md),
  [DR_DATABASE_CORRUPTION.md](./DR_DATABASE_CORRUPTION.md),
  [DR_VECTOR_INDEX_LOSS.md](./DR_VECTOR_INDEX_LOSS.md), [DR_BROKER_LOSS.md](./DR_BROKER_LOSS.md),
  [../10_DEPLOYMENT_DOCKER.md](../10_DEPLOYMENT_DOCKER.md),
  [../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md](../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md),
  [../28_KUBERNETES_HELM_DEPLOYMENT.md](../28_KUBERNETES_HELM_DEPLOYMENT.md)

Scope: the Compose host (staging or production) is gone or unrecoverable, a Kubernetes
cluster is lost, or a whole provider region is unavailable. With Compose, every data store
runs on that host, so this is also the loss of PostgreSQL, Qdrant, MinIO, RabbitMQ, and Redis
unless they are managed services elsewhere.

## Detection

- External uptime checks on the app and API hosts fail; the release workflow's smoke steps
  ("Smoke test production public endpoints") fail.
- `up` is 0 for every scrape target of the host or cluster in Prometheus, or Prometheus itself
  is unreachable (it may have been on the lost host).
- The provider's status page or console reports the instance, cluster, or region down.
- SSH to the host fails with a pinned host key that no longer answers.

## Decision owner

- Incident commander: declares the disaster, chooses between waiting for the provider and
  failing over, and owns customer communication.
- Platform owner: provisions the replacement host or cluster, DNS, and certificates.
- On-call engineer: runs the restore and deploy steps.
- Data protection lead: informed when the restore point loses customer data (RPO window).

## Steps

1. Declare the incident and freeze deploys (no release workflow runs except the recovery).
2. Decide: if the provider expects recovery within the recovery-time target, wait and monitor;
   otherwise fail over. Record the decision time (it starts the RTO clock in the log).
3. Choose the restore point for each store and write it in the incident record:
   - PostgreSQL: managed service with PITR and a cross-region replica: promote the replica or
     restore to a point in time in the surviving region ([DR_DATABASE_CORRUPTION.md](./DR_DATABASE_CORRUPTION.md)).
     Self-hosted on the lost host: the latest `postgres` backup from the off-host bucket.
   - Object storage: managed with cross-region replication: use the replica bucket. Otherwise
     the latest `objects` mirror.
   - Qdrant: the latest `qdrant` snapshots, or a rebuild from PostgreSQL
     ([DR_VECTOR_INDEX_LOSS.md](./DR_VECTOR_INDEX_LOSS.md)).
   - RabbitMQ and Redis hold no data that must survive: in-flight tasks are re-dispatched by the
     outbox relay and the document reaper ([DR_BROKER_LOSS.md](./DR_BROKER_LOSS.md)); rate
     limits, tickets, and caches rebuild themselves.
4. Provision the replacement:
   - Compose: a new host in a surviving zone or region with Docker and the deploy user; record
     its pinned SSH host key in `<ENV>_SSH_KNOWN_HOSTS` and update `<ENV>_SSH_HOST`.
   - Kubernetes: a new cluster with the operator add-ons listed in docs/28 (ingress
     controller, cert-manager, KEDA if used); recreate the namespace Secrets from the secret
     store (`secrets.existingSecret`, the backup key Secret).
5. Restore the data stores chosen in step 3 (commands in [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md)
   "Restore"). On Compose, bring up only the stores first:
   `docker compose -f docker-compose.production.yml up -d postgres qdrant minio redis rabbitmq`,
   restore into them, then continue.
6. Point the environment at the restored stores: update `DATABASE_URL`,
   `DATABASE_MIGRATION_URL`, `DATABASE_MAINTENANCE_URL`, `QDRANT_URL`, `MINIO_ENDPOINT`,
   `RABBITMQ_URL`, `REDIS_URL` in the env file secret or the Kubernetes Secret. Never reuse a
   URL of the lost environment by accident.
7. Deploy the last released images: run the release workflow's production deploy for the
   current release tag (or `target: rollback` with the previous tag, docs/14). The gate step
   checks backups; with a fresh replacement and no markers yet, the incident commander may set
   `DEPLOY_BACKUP_GATE=ssh` with fresh paths or record an explicit override in the incident
   before running it. Migrations run as part of the deploy (`alembic upgrade head`).
8. Move DNS for the app, API, MCP, and Matomo hosts to the new edge or ingress. ACME issues new
   certificates once DNS resolves (`EDGE_TLS_MODE=acme`, or cert-manager); with operator
   certificates, install them first.
9. Re-enable the backup jobs on the replacement (timer or CronJobs) and confirm the first run
   of each kind writes a marker.
10. Record the timeline, the restore points, and the measured RTO and RPO in
    [RESTORE_DRILL_LOG.md](./RESTORE_DRILL_LOG.md) (real restores are recorded too).

## Verification

- `GET /api/v1/health` and `/api/v1/ready` return 200 through the public host; the readiness
  body reports every dependency up.
- `python scripts/verify_postgres_restore.py --database-url ...` exits 0 against the restored
  database.
- A test user can sign in, open an existing document, and get a cited answer in chat; a new
  upload reaches `indexed`.
- `rudix_celery_queue_depth` drains; `outbox_messages` has no old `pending` rows
  (query in docs/27 "Outbox").
- Backup freshness is `fresh` for every kind within one schedule interval.
- Only 80 and 443 are reachable from outside (docs/11 "Edge and TLS").
