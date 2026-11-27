# v0.8.0 — Production Infrastructure

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../02_PRODUCTION_STACK.md](../02_PRODUCTION_STACK.md),
  [../10_DEPLOYMENT_DOCKER.md](../10_DEPLOYMENT_DOCKER.md),
  [../25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md](../25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md)

## 1. Purpose

Move from one host running single-instance containers to a deployment that terminates TLS,
runs replicas, survives the loss of a node, can be restored from backup, deploys without
downtime, and pages someone when it degrades.

Several items need the infrastructure decisions listed in the master plan section 8. Each
names a fallback that works on the current Compose deployment.

## 2. Target topology

```text
            CDN (static assets)
                   |
        Reverse proxy / ingress (TLS, security headers, WebSocket)
          |                 |                    |
     frontend xN         api xN               mcp xN
                            |
     +----------+-----------+-----------+-----------+
     |          |           |           |           |
  pooler      Redis      RabbitMQ     Qdrant      Object
  -> Postgres (cache,    (quorum      (replicated) storage
  primary +   pub/sub,   queues)
  replica     limits)
                            |
     worker-ingest / -graph / -sync / -eval / -default, beat x1
```

## 3. Work items

### R08-01 — Edge: TLS and reverse proxy (M)

- **Change:** Put a reverse proxy in front of frontend, API, and MCP. Terminate TLS with
  automated certificates. Stop publishing ports 3000, 8000, 8010, and 8081 on the host.
  Configure WebSocket and SSE timeouts, request size limits matching the upload cap, and
  access logs that exclude query strings.
- **Done when:** Only 80 and 443 are reachable from outside, and an external TLS scan passes.

### R08-02 — Orchestration and replicas (L, needs decision)

- **Recommended:** Kubernetes with a Helm chart under `deploy/helm/`: deployments for
  frontend, API, MCP, and each worker pool; one beat replica; a migrate job; readiness and
  liveness probes; pod disruption budgets; resource requests and limits.
- **Fallback:** Compose with scaled services behind the proxy from `R08-01`.
- **Either way:** Run the API as multiple processes or replicas. Graceful shutdown drains
  WebSockets with a close code the client treats as "reconnect" (`R05-13`).
- **Done when:** Killing one API replica during the load test causes no failed chat.

### R08-03 — Stateless API replicas (S)

- **Change:** Move `_ws_connection_counts` to Redis with per-replica heartbeat keys so a
  crashed replica's counts expire. Confirm nothing else is process-local: the JWKS cache may
  stay per process; the resume buffer and event stream already use Redis.
- **Done when:** Connection limits hold across two replicas in a test.

### R08-04 — Postgres: pooling, HA, and recovery (L, needs decision)

- **Change:**
  - Connection pooler in transaction mode (`DB_PGBOUNCER_MODE` from `R04-01`).
  - Managed Postgres, or a self-hosted primary with a streaming replica and automatic
    failover.
  - Continuous WAL archiving and point-in-time recovery.
  - Route read-only reporting and analytics queries (F153, F353, reports) to the replica
    through a second session factory. Requests that read their own writes stay on primary.
- **Done when:** A failover drill completes within the recovery-time target, and a
  point-in-time restore to a scratch instance is verified by a script.

### R08-05 — Qdrant, RabbitMQ, Redis, and object storage resilience (L)

- **Change:**
  - Qdrant: multi-node with replication factor 2 or more, snapshots to object storage.
  - RabbitMQ: three-node cluster with quorum queues (from `R06-05`).
  - Redis: persistence plus replica and failover. Separate logical instances for cache,
    rate limits and pub/sub, and Celery results, so cache eviction cannot drop a rate-limit
    key or a result.
  - Object storage: managed S3-compatible storage or distributed MinIO, with versioning.
- **Done when:** Losing any single data-store node during the load test loses no
  acknowledged work.

### R08-06 — Backups and restore drills (M)

- **Change:** Scheduled, encrypted, off-host backups for Postgres, Qdrant snapshots, object
  storage, and Neo4j where enabled. A restore runbook and a scripted quarterly restore drill
  that restores into a scratch environment and runs the smoke test. Replace the deploy-time
  backup gate (`R02-08`) with a freshness metric and alert.
- **Done when:** A drill has been run and recorded, and RPO and RTO are measured against the
  master-plan targets.

### R08-07 — Autoscaling (M)

- **Change:** Scale the API on in-flight requests and open streams, not CPU alone. Scale
  each worker pool on its queue depth and oldest-message age. Set minimums so a cold start
  never serves user traffic alone.
- **Done when:** A burst in the load test scales out and back without errors.

### R08-08 — Zero-downtime deploys and migration policy (M)

- **Change:**
  - Rolling updates with readiness gates.
  - Expand-contract migrations: additive in release N, backfill, switch reads, remove in
    release N+1 or later. Document it in `docs/CONTRIBUTING.md`.
  - CI check that fails a migration which drops or renames a column still referenced by the
    previous release's models, or takes an `ACCESS EXCLUSIVE` lock on a large table without
    an explicit override.
  - Migrations run as a job before the new version receives traffic. The previous version
    must work against the new schema.
- **Done when:** A deploy during the load test produces no failed requests.

### R08-09 — Observability in staging and production (M)

- **Change:** Deploy the Prometheus, Alertmanager, and Grafana stack from
  `infra/observability/` to staging and production with `METRICS_ENABLED=true` and the
  metrics token set. Give Alertmanager a real receiver and an escalation path. Enable
  Prometheus multiprocess mode in prefork workers so child-process counters are exported.
  Then add a beat heartbeat alert (deferred from `R02-03` because it needs those counters).
  Add SLO recording rules and multi-window burn-rate alerts for availability, chat latency,
  ingestion latency, and queue age. Ship logs to an aggregator with the request ID indexed.
- **Done when:** A synthetic failure pages the on-call receiver, and every master-plan
  target has a dashboard panel.

### R08-10 — Distributed tracing (M, needs approval)

- **Change:** OpenTelemetry tracing across frontend proxy, API, Celery tasks (context
  propagated in task headers), Postgres, Redis, Qdrant, and LLM calls. Link trace IDs to the
  existing request ID and Langfuse trace. Sampling is a setting. Spans never contain document
  text, prompts, or tokens.
- **Fallback:** Request-ID correlation in logs plus Langfuse.

### R08-11 — Secrets and configuration (M)

- **Change:** Move secrets from a whole-file `.env` GitHub secret to a secret manager with
  per-secret access and rotation. Document rotation for JWT keys, provider keys, and the
  webhook signing secret. Serve frontend runtime configuration from the server at request
  time so one frontend image is promoted across environments instead of one per environment.
- **Done when:** Staging and production run the same image digests for every service.

### R08-12 — Environment parity and CDN (S)

- **Change:** Make dev, staging, and production compose or chart values differ only in
  scale and secrets: the same optional services (ClamAV, Neo4j, Matomo) are present or
  explicitly disabled in each. Serve `/_next/static` and public assets through a CDN with
  immutable caching.

### R08-13 — Disaster recovery runbook (S)

- **Change:** Add `docs/` runbooks for: region or host loss, database corruption, vector
  index loss (rebuild from Postgres chunks and the embedding cache), broker loss, and
  credential compromise. Each lists detection, decision owner, steps, and verification.

## 4. Exit criteria

- Load test at target scale with one node of each tier killed: SLOs hold.
- Restore drill passed; RPO and RTO measured.
- Deploy under load with zero failed requests.
- Every unchecked item in `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` that concerns
  infrastructure is either checked or has an owner and a version.

## 5. Failure Modes and Recovery

Covered by the runbooks in `R08-13`. The specific new risk in this version is split-brain or
lag on replicas: read-replica routing must be limited to queries that tolerate staleness, and
replica lag is alerted.

## 6. Security Considerations

- Network policy: data stores are reachable only from application pods or containers.
- TLS between services where the platform supports it; always for managed data stores.
- Backups are encrypted and access-logged. Restores into scratch environments use masked or
  synthetic data unless the drill requires production data, in which case the environment
  has production access controls.
- Metrics and tracing endpoints require authentication and carry no document content.

## 7. Change Notes

- 2026-11-26: Initial version.
