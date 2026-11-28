# v0.8.0 — Detailed Implementation Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Implemented on `develop` (all nine packages merged; see section 11)
- `Last Updated`: 2026-11-28
- `Related Docs`: [V0_8_0_PRODUCTION_INFRASTRUCTURE.md](./V0_8_0_PRODUCTION_INFRASTRUCTURE.md),
  [V0_7_0_IMPLEMENTATION_PLAN.md](./V0_7_0_IMPLEMENTATION_PLAN.md),
  [V0_6_0_IMPLEMENTATION_PLAN.md](./V0_6_0_IMPLEMENTATION_PLAN.md),
  [01_EXECUTION_PLAN.md](./01_EXECUTION_PLAN.md),
  [../10_DEPLOYMENT_DOCKER.md](../10_DEPLOYMENT_DOCKER.md),
  [../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md](../14_GITHUB_ACTIONS_CI_CD_PIPELINE.md),
  [../11_SECURITY_AND_PRODUCTION_CHECKLIST.md](../11_SECURITY_AND_PRODUCTION_CHECKLIST.md),
  [../12_EVALUATION_AND_MONITORING.md](../12_EVALUATION_AND_MONITORING.md)

## 1. Purpose

Turn the `0.8.0` spec into nine work packages with exact files, shared-file anchors, tests,
and owners. Every reference was read on `develop` at `9eb0acd3` (`0.2.0` to `0.7.0` merged, not
tagged; `27c2e2ef` later changed only the documents page bundle). Line numbers drift; search
for the quoted symbol.

Most of `0.8.0` is infrastructure that cannot run on a development machine. This release builds
the repository part: a Helm chart, hardened Compose files, an edge proxy configuration,
settings that default to current behaviour, scripts with tests, alert and recording rules,
CI checks, and runbooks. Provisioning, DNS, certificates, a cluster, managed data stores, a
secret manager, a CDN, a paging service, drills, and load tests are operator steps (section 8).

Evidence rule: no latency, RPO, RTO, failover, drill, scan, or load figure is written down in
this release, because none can be measured here. Exit criteria that need them stay open
(section 9).

## 2. Decisions taken

The owner asked for the roadmap to run to the end, taking the recommended option where a
decision is open.

| Decision | Option taken | Why | Fallback that remains |
|---|---|---|---|
| Orchestrator (`R08-02`) | Kubernetes, Helm chart `deploy/helm/rudix/` | Recommended; rolling deploys, PDBs, autoscaling | Compose (`deploy/compose/*`) stays supported, scaled behind the edge proxy; Terraform and `deploy_compose_remote.sh` keep working |
| Postgres (`R08-04`) | Managed Postgres with point-in-time recovery | Recommended; failover and WAL archiving are the provider's | Self-hosted primary plus streaming replica and WAL archiving: documented in docs/28, not built; the Compose `postgres` service stays |
| Pooler (`R08-04`) | PgBouncer in transaction mode (`DB_PGBOUNCER_MODE` from `R04-01`); the managed provider's pooler when it has one | Cheap; settings already support it | Opt-in Compose profile `pooler` and a chart Deployment that defaults off |
| Tracing (`R08-10`) | OpenTelemetry in the backend, off by default; dependencies approved by the owner | Recommended | `TRACING_ENABLED=false` keeps request-ID logs plus Langfuse |
| Collector or vendor | None; `OTEL_EXPORTER_OTLP_ENDPOINT` is a setting | No account | Nothing is exported while unset |
| Compose edge proxy (`R08-01`) | Caddy (automatic ACME certificates) in staging and production compose | Spec asks for automated certificates; no extra tooling | `EDGE_TLS_MODE=files` with operator-provided certificates |
| Kubernetes edge | `Ingress` for an NGINX ingress controller plus cert-manager annotations (both operator-installed) | Most common; values are placeholders | Any controller via `ingress.className` and annotations |
| Autoscaling (`R08-07`) | KEDA `ScaledObject`s with Prometheus triggers; plain `HPA` on CPU as an alternative mode | Scales on in-flight requests, streams, queue depth and wait | `autoscaling.enabled=false` (fixed replicas) |
| Secrets (`R08-11`) | Chart reads an existing Kubernetes Secret; optional External Secrets Operator template (off) | No secret manager is provisioned | Compose keeps the whole-file env secret |
| Redis roles (`R08-05`) | `REDIS_URL` (state: rate limits, pub/sub, tickets, resume buffer, cache version keys), optional `REDIS_CACHE_URL` (cached values), optional `CELERY_RESULT_BACKEND_URL` | Cache eviction cannot drop a rate-limit key, a version key, or a result | Both unset: one Redis, as today |
| Backups (`R08-06`) | Python runner on the worker image, AES-256-GCM client-side encryption (`cryptography`, already a dependency), `pg_dump` from the `postgres:16` image, markers in the backup bucket | No new image or dependency | `DEPLOY_BACKUP_GATE=ssh` (default) keeps the `R02-08` gate |
| Drain close code (`R08-02`) | `1012` (service restart); uvicorn 0.54 already sends it | The client (`ws-reconnect.ts`) treats it as retryable | — |
| Log shipping (`R08-09`) | JSON logs on stdout with `request_id` and `trace_id`; aggregator is an operator choice | No account | Container logs on the host |
| Package count | Nine (section 3 of the execution plan says eight; `0.7.0` used nine) | Thirteen items, four parallel chains | — |

## 3. Plan check: what the code confirmed or changed

| Item | Result |
|---|---|
| R08-01 | **Changed.** Staging and production publish `3000`, `8000`, `${MCP_HTTP_PORT}` and (production) `8081`. `deploy_compose_remote.sh` checks health with `curl http://127.0.0.1:8000/...` on the host, which breaks once `8000` is unpublished; it moves to `docker compose exec -T api python -c ...` as Terraform already does. Matomo must stay reachable by browsers, so it gets its own edge host. The API has no forwarded-header configuration; uvicorn honours `FORWARDED_ALLOW_IPS`. `app/auth/dependencies.py` reads the leftmost `X-Forwarded-For` for `last_used_ip`; Caddy replaces client-sent forwarding headers by default, which the edge test asserts. |
| R08-02 | **Changed.** uvicorn 0.54 closes open WebSockets with `1012` when shutdown starts; the client reconnects on it only while a run is in flight (an idle socket reconnects on next use). A dropped run keeps going in its grace window (`keep_run_alive_after_drop`, `_GRACE_WATCHERS`), but `lifespan` then closes Redis and the engine, cutting it. The API image runs one uvicorn process; replicas, not `--workers`, give multiple processes, so the API needs no Prometheus multiprocess mode. `/api/v1/ready` fails when any dependency (Qdrant, MinIO, RabbitMQ, Neo4j) is down, so as a Kubernetes readiness probe it would take every pod out on one blip; an additive `READINESS_REQUIRED_DEPENDENCIES` (default: all, as today) fixes it. |
| R08-03 | **Changed.** `_ws_connection_counts` (`interfaces/http/chat.py`) is the only per-user limit kept in process. The realtime stream already holds leases in Redis (`acquire_connection_slot` on `app/rate_limit/concurrency.py`); WebSocket slots reuse that semaphore with a lease refreshed by the existing heartbeat, which gives the spec's "a crashed replica's counts expire" without separate per-replica keys. `WS_CHAT_CONNECTION_LIMIT_BACKEND=memory` (default) keeps today's behaviour. |
| R08-04 | **Changed.** Reporting routes take `get_db_session`, and `get_current_principal` binds the tenant on that session; a replica session needs its own dependency that binds the same tenant. Routes eligible for the replica (read-only, staleness-tolerant): `GET /admin/usage/dashboard` (F153), `GET /admin/usage-adoption/{summary,charts,funnel,users,export}` (F353), `GET /reports`, `GET /reports/answer-quality`. `POST /reports/events` and every other route stay on primary. RLS context works on a hot standby (`set_config` is allowed read-only). The restore verification script is built in `A2` with the backups so chains stay independent. |
| R08-05 | **Changed.** `QDRANT_REPLICATION_FACTOR` and `QDRANT_SHARD_NUMBER` exist (`app/clients/qdrant_tuning.py`); a write consistency factor does not. One Redis client serves cache, rate limits, pub/sub and Celery results (`redis_result_backend_url()` returns `REDIS_URL`). Cache invalidation bumps version keys with `INCR` (`cache_invalidation._bump`): those keys must live with the state, not the evictable cache. Quorum queues exist opt-in (`CELERY_QUEUE_TYPE`, `R06-05`); the cut-over stays an operator step. |
| R08-06 | **Changed.** The deploy gate (`check_remote_backups.sh`) checks file ages on the host over SSH. "Replace with a freshness metric" is additive here: backups write markers to the backup bucket, a beat task exports their age, and the deploy gate can read the same markers (`DEPLOY_BACKUP_GATE=marker`); the SSH gate stays the default until an operator switches. Neo4j Community cannot dump online; Neo4j backup is an operator step. |
| R08-07 | **Changed.** No oldest-message-age metric exists from the broker; `rudix_celery_queue_wait_seconds` (publish-to-start, `R06-05`) and `rudix_celery_queue_depth` stand in. API signals: `rudix_http_requests_in_progress`, `rudix_realtime_connections`, and a new `rudix_chat_ws_connections` (S1 declares it, B1 sets it). |
| R08-08 | **Changed.** No release tag exists, so "the previous release's models" is a git ref given to the check (`--base-ref`; CI uses the pull request base). 104 migrations exist; `20261128_0003` already uses `CONCURRENTLY`. Existing findings go in an allowlist with reasons. |
| R08-09 | **Changed.** Worker metrics come from `start_http_server` in `worker_ready` (the prefork parent), without authentication, so counters from child processes (`task_prerun`, every task metric) are never exported. `prometheus.yml` scrapes the API without a bearer token although `METRICS_REQUIRE_AUTH` exists. The Alertmanager receiver is empty. Rules live in one `alerts.yml`. |
| R08-10 | **Changed.** `opentelemetry-api` 1.45.2 is already in `uv.lock` (transitive); the SDK, exporter and instrumentations are not. The frontend proxy has no tracing and adding Next.js OpenTelemetry packages is not approved: the edge proxy and the API accept `traceparent`; frontend server spans are deferred. |
| R08-11 | **Changed.** 152 `NEXT_PUBLIC_*` names; 34 source files read `process.env.NEXT_PUBLIC_*` directly, which Next inlines at build. Security headers (CSP `connect-src` with the API origin) are evaluated at build in standalone mode. Prerendered public pages take `metadataBase` and canonical URLs from `NEXT_PUBLIC_PUBLIC_SITE_URL` or `NEXT_PUBLIC_APP_URL` at build. One image across environments therefore conflicts with static prerendering unless both environments share the canonical site URL; see section 6. `APP_AUTH_SECRET` is a single HMAC key (no overlap during rotation) and is also the development fallback for connector credential encryption. |
| R08-12 | **Changed.** Staging runs Neo4j and no Matomo; production runs Matomo and no Neo4j; both run ClamAV. Parity is reached with profiles: both files define the same services, and `COMPOSE_PROFILES` chosen per environment by the deploy enables them. `assetPrefix` is build-time, so a CDN host shared by staging and production is required for one image. |
| R08-13 | Confirmed: no runbook exists for host loss, database corruption, vector index loss, broker loss, or credential compromise. `scripts/vector_index.py` (`R06-08`) and the embedding cache (`R06-06`) support the vector rebuild. |
| Docs | The spec's deployment doc is `docs/10_DEPLOYMENT_DOCKER.md` (docs/08 is the service guide). New: `docs/28_KUBERNETES_HELM_DEPLOYMENT.md` (S1) and `docs/runbooks/` (A2). |
| Migrations | None needed. Alembic head stays `20261128_0003`. If one becomes unavoidable it goes into chain C as `20261129_0001` with `down_revision = "20261128_0003"`; any other package stops and reports. |

## 4. Sequence

| Chain | Order | Task | Items | Model | Review |
|---|---|---|---|---|---|
| S | 1 | S1 | Foundation: chart skeleton, helpers, values anchors, structural test harness, CI job, rule directory, settings stubs, shared metrics | opus | data |
| A | 1 | A1 | R08-01 edge proxy and TLS; R08-12 environment parity; R08-05 Compose topology (pooler, Redis split, MinIO versioning); R08-02 Compose fallback | opus | data |
| A | 2 | A2 | R08-06 backups, freshness, restore verification and drill; R08-05 data-store resilience settings and docs; R08-13 runbooks | opus | data |
| B | 1 | B1 | R08-03 Redis connection limits; R08-02 graceful shutdown; readiness scope; R08-05 Redis roles | opus | api |
| B | 2 | B2 | R08-09 multiprocess metrics, authenticated scrape, beat heartbeat, SLO and burn-rate rules, Alertmanager routing, dashboard | opus | api |
| B | 3 | B3 | R08-10 OpenTelemetry tracing | opus | api |
| C | 1 | C1 | R08-02 chart workloads; R08-07 autoscaling; R08-08 rollout and migrate job; network policies | opus | data |
| C | 2 | C2 | R08-04 replica routing, lag, pooler values; R08-08 migration safety check and policy | opus | data |
| D | 1 | D1 | R08-11 secrets, rotation, request-time frontend configuration; R08-12 CDN | opus | api |

S1 runs first and alone; A, B, C, and D start after S1 is merged. Model reasons: every package
touches one of secrets, network exposure, metrics or tracing authentication, primary versus
replica routing, connection limits across replicas, migration safety, or graceful shutdown;
each branch is reviewed by Opus.

## 5. Shared files and contracts

### 5.1 Owners and anchors

Every task re-reads a shared file before editing, edits only its anchor with `Edit`, never
rewrites or reformats a shared file, and re-reads after a failed `Edit`. Anchors use the
prefix `v080-` because `0.6.0` left `# anchor: A2` style markers in the same files.

| File | Task: anchor |
|---|---|
| `deploy/helm/rudix/values.yaml` | S1 writes every top-level key with a `# owner:` comment. Owners: S1 `global`, `image`, `config`, `secrets`, `serviceAccount`, `podSecurityContext`, `containerSecurityContext`, `metrics` (shape only); A1 `ingress`; A2 `backup`, `dataStores`; C1 `frontend`, `api`, `mcp`, `workers`, `beat`, `migrations`, `autoscaling`, `networkPolicy`, `podDisruptionBudget`, `rollout`, `connectionBudget`; C2 `database`, `pgbouncer`; B2 `metrics.serviceMonitor`, `metrics.workers`; B3 `tracing`; D1 `runtimeConfig`, `cdn`, `secrets.externalSecret`. `config.env` keys go under `# v080-<task>` comments. S1 renders a frontend ConfigMap from `runtimeConfig.env` (empty until D1), which C1's frontend Deployment mounts with `envFrom`. |
| `values-staging.yaml`, `values-production.yaml`, `ci/all-features-values.yaml` (chart) | Same keys and comments as `values.yaml`; staging and production differ only in scale, hosts, and secret names (R08-12). |
| `templates/_helpers.tpl` | S1 only. Other tasks add `templates/_<task>.tpl`. |
| `templates/*` | One file or directory per workload or feature: A1 `ingress.yaml`; A2 `backup/`; C1 `frontend/`, `api/`, `mcp/`, `workers/`, `beat/`, `migrations/`, `networkpolicy/`, `autoscaling/`; C2 `pgbouncer/`; B2 `metrics/`; D1 `externalsecret.yaml`. |
| `deploy/compose/docker-compose.{staging,production}.yml` | A1, then A2 (same chain). No other task edits them. |
| `docker-compose.yml` (local) | Not edited in `0.8.0`, except A1 may add opt-in profiles; no new default service. |
| `deploy/scripts/check_compose_config.sh` | A1 and A2 (chain A). B2 adds its own `check_observability_config.sh`. |
| `deploy/terraform/*`, `deploy/scripts/deploy_compose_remote.sh` | A1, then A2. |
| `.github/workflows/ci.yml` | S1 adds job `deploy-config` (steps "Set up Helm", "Lint and render Helm chart", "Validate rendered manifests", "Check compose files") and "Set up Helm" before "Run backend tests" in `backend`. A1 adds "Validate Caddyfile" after "Check compose files"; B2 adds "Check Prometheus rules", "Check Alertmanager config", "Check observability compose" after "Validate rendered manifests"; C2 sets `fetch-depth: 0` on the `backend-alembic` checkout and adds "Check migration safety" after "Apply and roll back migrations". |
| `.github/workflows/release.yml` | A1: `TF_VAR_compose_profiles` in the two Terraform steps; A2: the step that runs `check_remote_backups.sh` gains `DEPLOY_BACKUP_GATE`; D1: optional single frontend image under `vars.RUDIX_FRONTEND_IMAGE_MODE == 'single'`. |
| `infra/observability/prometheus/prometheus.yml` | S1 adds `"/etc/prometheus/rules/*.yml"` to `rule_files`; B2 owns the rest. `alerts.yml`: B2 only. |
| `infra/observability/prometheus/rules/` | A2 `backups.yml`; B2 `slo-recording.yml`, `slo-burn-rate.yml`, `beat.yml`; C2 `database.yml`. Each file passes `tests/test_prometheus_rules.py` (S1). |
| `infra/observability/grafana/dashboards/` | B2 only (new `08-rudix-slo-targets.json`). |
| `backend/app/core/config.py` (`Settings` bases) | S1 only: registers `DeploymentSettings` (`settings/deployment.py`, B1 fills), `TracingSettings` (`settings/tracing.py`, B3), `BackupSettings` (`settings/backup.py`, A2). Others: B1 end of `RedisRateLimitSettings` and `CelerySettings`; B2 end of `ObservabilitySettings`; C2 end of `DatabaseSettings`; D1 end of `AuthSettings`; A2 after `qdrant_replication_factor` in `workers.py`. |
| `backend/app/core/settings/snapshot.py` | S1 adds an `"infrastructure"` dict with `# anchor: v080-<task>` lines; only booleans (`*_set`) and sanitized values, never URLs with credentials. |
| `backend/app/core/metrics_infra.py` (S1) | Declares `rudix_chat_ws_connections` (Gauge, `livesum`), `rudix_beat_heartbeat_timestamp_seconds` (Gauge, `max`), `rudix_backup_last_success_timestamp_seconds{kind}` (Gauge, `max`), `rudix_db_replica_lag_seconds` (Gauge, `max`). Setters are added by B1, B2, A2, C2. `app/core/metrics.py` and the other metric modules: only B2 edits them, adding `multiprocess_mode` to gauges; names and labels never change. |
| `backend/Makefile` | C2 adds `check-migration-safety` after `check-revisions`. No other task edits it. |
| `backend/app/workers/celery_app.py` | S1 adds `# anchor: v080-A2` and `# anchor: v080-B2` in `INCLUDE`, `TASK_ROUTES`, `BEAT_SCHEDULE`. B2 owns `_on_worker_ready` and `_shutdown_worker`; B3 adds tracing setup in `_init_worker_process` (signal `worker_process_init`) after B2. |
| `backend/app/core/lifespan.py`, `app/main.py`, `app/api/health.py` | Chain B only (B1, then B3). |
| `backend/pyproject.toml`, `backend/uv.lock` | B3 only, together, with `uv lock`. |
| `.env.example` (root) | S1 adds `# --- Production infrastructure (0.8.0) ---` with `# anchor: v080-A1` … `# anchor: v080-D1`. |
| `docs/28_KUBERNETES_HELM_DEPLOYMENT.md` (S1) | One `##` section per task, created empty by S1 with a `<!-- v080-<task> -->` marker. |
| `docs/10_DEPLOYMENT_DOCKER.md` | A1 `## Edge proxy, scaling, and environment parity (0.8.0)` before `## Backup strategy`; A2 rewrites `## Backup strategy`; C1 updates the `## Scaling strategy` table; D1 adds a CDN paragraph at the end of `## Frontend deployment`. |
| `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` | A1 new `## Edge and TLS` before `## Security headers`; A2 new `## Backups and restore` before `## Data deletion`; B2 bullets under `### Observability`; B3 new `## Tracing` before `## Logging safety`; C1 bullets under `### Deployment`; C2 bullets under `### Database`; D1 subsection `### Rotation` at the end of `## Secrets` and one bullet at the end of `## Security headers` (request-mode CSP). Every new unchecked bullet ends with `(operator, 0.8.0)`. |
| `docs/12_EVALUATION_AND_MONITORING.md` | One `###` subsection per task (A2, B1, B2, B3, C2) before `## Continuous evaluation`. |
| `docs/CONTRIBUTING.md` | C2 only (`## Database migrations`). |
| `docs/README.md` | S1 adds docs/28 as item 29 under "Architecture and Implementation"; A2 adds `docs/runbooks/*` under "Setup and Operations". |
| `backend/README.md`, `frontend/README.md` | One bullet list per task at the end of the section its settings belong to. |
| `docs/CHANGELOG.md` | One line per task under `[Unreleased]` `### Added`, directly after the line starting "- `docs/roadmap/V0_8_0_IMPLEMENTATION_PLAN.md`". |
| Frontend (`frontend/**`) | D1 only. |

### 5.2 Contracts between chains

1. **Worktrees and checks.** Branch `feat/v0.8.0-<task>` in `../rudix-v080-<task>` from the
   current `develop`. A branch that changes `backend/`, `infra/` rule files, or `deploy/` files
   read by tests runs `cd backend && make install`, the SQLite suite, and the Postgres lane on
   database `rudix_test_<chain>` at `127.0.0.1:55432`; if `rudix-test-pg` is not running it
   reports that and does not start it. A branch that changes the chart or compose files runs
   `deploy/scripts/check_helm_chart.sh` and `deploy/scripts/check_compose_config.sh`. Frontend
   checks only in D1. No container is started, stopped, or created.
2. **Chart names (S1).** `rudix.fullname`, `rudix.componentName <component>` (`frontend`, `api`,
   `mcp`, `worker-<pool>`, `beat`, `migrate`, `pgbouncer`, `backup-<kind>`),
   `rudix.labels`, `rudix.selectorLabels` with `app.kubernetes.io/component`, `rudix.image
   <component>` (digest wins over tag), `rudix.envFrom` (the `config` ConfigMap plus
   `secrets.existingSecret`; values files never hold secret values). Service ports by name:
   frontend `http` 3000, api `http` 8000, mcp `http` 8010, workers `metrics` 9808. Every pod
   runs as non-root with a read-only root filesystem and a writable `/tmp` `emptyDir`.
3. **Structural tests (S1).** `backend/tests/helm_support.py` `render_chart(values_files,
   set_values) -> list[dict]` runs `helm template` (skip with a clear reason when `helm` is
   missing; CI installs it); `backend/tests/test_helm_chart_*.py` per task. Common assertions
   (S1): every rendered object has the standard labels; no `hostPort`, `hostNetwork`, or
   `privileged`; no literal secret values (keys matching `PASSWORD|SECRET|TOKEN|KEY` only in
   `secretKeyRef` or `envFrom.secretRef`).
4. **Rule files (S1).** `tests/test_prometheus_rules.py` parses every file under
   `infra/observability/prometheus/` (rules) and fails when an expression names a `rudix_*`
   series that the application registry does not export (suffixes `_bucket`, `_sum`,
   `_count`, `_total` resolved), when an alert lacks `severity` and `summary`, or when a name
   repeats.
5. **Shutdown (B1 sets, C1 and A1 use).** `API_SHUTDOWN_DRAIN_SECONDS` (default `0`, current
   behaviour) bounds how long `lifespan` waits for dropped runs before closing clients. Chart
   and Compose set `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN` and the drain so that preStop sleep +
   graceful timeout + drain < `terminationGracePeriodSeconds` / `stop_grace_period`.
6. **Readiness (B1 sets, C1 uses).** `READINESS_REQUIRED_DEPENDENCIES` (comma list; unset =
   every dependency, as today). Chart readiness probe `GET /api/v1/ready` with
   `READINESS_REQUIRED_DEPENDENCIES=postgres,redis`; liveness `GET /api/v1/health`.
7. **Redis roles (B1).** State keys (rate limits, semaphores, tickets, resume buffer, realtime,
   usage touch, cache version keys) always on `REDIS_URL`; cached values on `REDIS_CACHE_URL`
   when set; Celery results on `CELERY_RESULT_BACKEND_URL` when set. A1's Compose profile
   `redis-split` and C1's values only set these variables.
8. **Metrics scrape (B2).** `/metrics` on the API and port 9808 on workers both require
   `Authorization: Bearer <METRICS_BEARER_TOKEN>` when `METRICS_REQUIRE_AUTH=true`; the chart
   and production Compose always set it true when metrics are enabled. Prometheus reads the
   token from a file (`authorization.credentials_file`).
9. **Backup markers (A2).** `s3://<BACKUP_BUCKET>/<BACKUP_PREFIX>/<kind>/latest.json` with
   `completed_at`, `object_key`, `size_bytes`, `sha256`, `format_version`; no secret, path, or
   hostname of the source. Kinds: `postgres`, `qdrant`, `objects`, `neo4j` (marker only when an
   operator backup writes it).
10. **Restore verification (A2).** `backend/scripts/verify_postgres_restore.py --database-url
    ... [--expect-revision 20261128_0003] [--manifest file]` exits `0` only when the schema
    is at the expected head, required RLS policies and indexes exist, and manifest row-count
    floors hold. It prints table names and counts only.
11. **Replica session (C2).** `get_reporting_db_session` binds the same tenant as the primary
    session of the request and is used only by the routes in section 3; it falls back to the
    primary when no replica URL is set or the sampled lag exceeds the limit.

## 6. Steps per item (summary; the task briefs hold the detail)

- **S1:** chart skeleton (`Chart.yaml` `0.8.0`, values with owners, helpers, ConfigMap,
  ServiceAccount), `deploy/scripts/check_helm_chart.sh` (lint plus `helm template` for the
  defaults, staging, production, and every `ci/*-values.yaml`), CI job, rule directory and rule
  test, settings stubs, `metrics_infra.py`, `.env.example` and docs anchors, docs/28 skeleton.
- **A1 (R08-01, R08-12, R08-05 Compose, R08-02 Compose):** `deploy/compose/edge/Caddyfile`
  with hosts from `RUDIX_APP_HOST`, `RUDIX_API_HOST`, `RUDIX_MCP_HOST`, `RUDIX_MATOMO_HOST`,
  ACME email from `EDGE_ACME_EMAIL`, `request_body max_size` from the upload cap, WebSocket and
  SSE timeouts, access logs with query strings removed, `X-Robots-Tag: noindex` when
  `EDGE_NOINDEX=true`; service `edge` publishing only 80 and 443; no host ports elsewhere;
  `FORWARDED_ALLOW_IPS`; profiles `graph`, `analytics`, `pooler`, `redis-split`; MinIO
  versioning flag; `COMPOSE_PROFILES` through Terraform and the remote script; chart
  `ingress.yaml`. Compose fallback for replicas: `docker compose up --scale api=N`.
- **A2 (R08-06, R08-05, R08-13):** `backend/scripts/backup/` runner (encrypt, upload, marker),
  restore and decrypt tool, `verify_postgres_restore.py`, `deploy/scripts/restore_drill.sh`,
  Compose profile `backup`, chart CronJobs, beat task `ops.backups.check_freshness`, alert
  rules, `DEPLOY_BACKUP_GATE=ssh|marker`, `QDRANT_WRITE_CONSISTENCY_FACTOR`, data-store
  guidance (Qdrant RF 2+, RabbitMQ three nodes with quorum queues, Redis replica and
  persistence, versioned S3), runbooks under `docs/runbooks/`.
- **B1 (R08-03, R08-02, R08-05):** Redis-leased WebSocket slots with heartbeat refresh,
  `rudix_chat_ws_connections`, shutdown drain, readiness scope, Redis roles, audit of
  process-local state.
- **B2 (R08-09):** multiprocess collection in prefork workers (`PROMETHEUS_MULTIPROC_DIR`
  prepared by `app/workers/pools.py`, gauges with explicit modes, `mark_process_dead`),
  authenticated worker metrics server, scrape with token files, `ops.beat.heartbeat`, SLO
  recording rules and multi-window burn-rate alerts from `infra/observability/slo_targets.yml`,
  Alertmanager routes with placeholder receivers read from files, deploy overlay for the
  observability Compose stack, ServiceMonitor template (off), dashboard 08 with a panel per
  master-plan target.
- **B3 (R08-10):** `app/core/tracing.py`, settings, FastAPI, SQLAlchemy, Redis, Celery, and
  httpx instrumentation, manual spans for Qdrant and LLM calls, a span processor that drops
  attributes outside an allowlist, `trace_id` in logs and Langfuse metadata, in-memory exporter
  tests for redaction and Celery header propagation.
- **C1 (R08-02, R08-07, R08-08):** Deployments, Services, PDBs, probes, resources, beat with
  one replica and `Recreate`, migrate Job as a pre-install and pre-upgrade hook, rolling
  update with `maxUnavailable: 0`, KEDA and HPA templates, NetworkPolicies (default deny,
  data stores reachable only from application pods), connection-budget render check.
- **C2 (R08-04, R08-08):** replica settings, engine and session factory, lag sampler and
  routing, read-only enforcement, pooler Deployment (off), replica lag alert, migration safety
  check with allowlist and override marker, CI step, expand-contract policy in CONTRIBUTING.
- **D1 (R08-11, R08-12):** `APP_AUTH_SECRET_PREVIOUS` (verify-only), rotation runbooks for JWT,
  provider, webhook, bot, metrics, and backup keys, ExternalSecret template,
  `NEXT_PUBLIC_RUNTIME_CONFIG_SOURCE=build|request` (default `build`) with
  `/runtime-config.js`, an allowlisted accessor, CSP from the proxy in request mode,
  `NEXT_PUBLIC_ASSET_PREFIX` and cache headers for public assets, optional single-image build.

**Conflict in R08-11 and the step taken.** Static public pages bake `metadataBase`, canonical,
hreflang, and the CSP at build. A request-time configuration cannot change prerendered HTML
without making the pages dynamic, which `0.7.0` forbids. The step taken: request mode changes
only client-side values and moves the CSP to the proxy; canonical URLs stay build-time and come
from `NEXT_PUBLIC_PUBLIC_SITE_URL`. One image for staging and production therefore needs the
owner to accept the production canonical URL on staging (with `EDGE_NOINDEX=true` on the
staging edge) and one CDN host for both. Until then the release workflow keeps building one
frontend image per environment (the default).

## 7. Verification for the release

```bash
cd backend && make install && make lint && make test && make test-cov
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://rudix:rudix@127.0.0.1:55432/rudix_test make test-postgres
cd backend && make check-revisions && .venv/bin/python scripts/check_migration_safety.py --all
cd backend && .venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json
deploy/scripts/check_helm_chart.sh && deploy/scripts/check_compose_config.sh
deploy/scripts/check_observability_config.sh
cd frontend && npm ci && npm run format && npm run lint && npm run typecheck && npm run test:coverage
cd frontend && npm run build && node scripts/check-prerendered-routes.mjs && npm run api:check
cd frontend && node scripts/check-bundle-budgets.mjs && PLAYWRIGHT_USE_BUNDLED_BROWSER=true npx playwright test
```

Coverage stays at or above the ratchets (backend 82.4; frontend statements 68.6, branches
60.8, functions 62.1, lines 69.5). `alembic heads` reports `20261128_0003`. The prerender check
finds all 144 static routes and the 162 parity tests pass. The bundle budget check passes
(`/documents` was brought back within budget at `27c2e2ef`); D1 must not add to any route's
first-load size in the default build and never raises a budget. First exercised in CI, not here: `kubeconform`, `promtool check/test rules`,
`amtool check-config`, `caddy validate`, `terraform fmt/validate`.

## 8. Operator steps (not done in the repository)

1. Provision a cluster, an NGINX ingress controller, cert-manager with an ACME issuer, KEDA
   (if autoscaling), and the Prometheus Operator (if ServiceMonitors); fill the placeholder
   hosts, issuer, storage classes, and secret names in `values-staging.yaml` and
   `values-production.yaml`.
2. Create managed Postgres with PITR and a read replica; record the provider's RPO and
   failover behaviour; create `rudix_app`, `rudix_maintenance`, and a read-only replica role
   (`deploy/sql/provision_roles.sql`); set `DATABASE_URL`, `DATABASE_REPLICA_URL`, pooler.
3. Run Qdrant with replication factor 2 or more, a three-node RabbitMQ cluster (then the
   quorum cut-over of docs/27), Redis with persistence and a replica (two instances or logical
   databases for state and cache), and versioned S3-compatible storage.
4. Create the backup bucket in another account or region, its encryption key, and the backup
   credentials; enable the backup CronJobs or Compose profile; switch
   `DEPLOY_BACKUP_GATE=marker` once markers are fresh.
5. DNS for the app, API, MCP, Matomo, and Grafana hosts; open only 80 and 443; run an external
   TLS scan and record the result in the edge section of docs/11.
6. Choose a secret manager (or keep Kubernetes Secrets), move each secret out of the
   whole-file `*_ENV_FILE` GitHub secrets, and rotate every secret once using docs/runbooks.
7. Choose a paging service and a log aggregator; write their endpoints into the Alertmanager
   receiver files and the log shipper; fire a synthetic alert and confirm the page.
8. Choose an OTLP collector or vendor; set `TRACING_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`,
   and the sampling ratio on staging.
9. Choose a CDN; set `NEXT_PUBLIC_ASSET_PREFIX`; decide the canonical URL for staging
   (section 6) before enabling the single frontend image.
10. Run the load test at target scale, kill one replica of each tier, deploy under load, run
    the failover drill and the first restore drill, and record RPO and RTO in
    `docs/runbooks/RESTORE_DRILL_LOG.md`.

## 9. Exit criteria that stay staging-only

- Only 80 and 443 reachable from outside; external TLS scan passes (`R08-01`).
- Killing one API replica during the load test causes no failed chat (`R08-02`).
- Losing any single data-store node during the load test loses no acknowledged work (`R08-05`).
- Failover drill within the recovery-time target; point-in-time restore verified by the script
  against a real scratch instance (`R08-04`).
- Restore drill run and recorded; RPO and RTO measured (`R08-06`).
- A burst scales out and back without errors (`R08-07`); a deploy during the load test produces
  no failed requests (`R08-08`); a synthetic failure pages the on-call receiver (`R08-09`).
- Staging and production run the same image digests for every service (`R08-11`; needs the
  section 6 decisions for the frontend).
- Unchecked infrastructure items in docs/11 have an owner and a version (release integrator
  annotates them).

Checked here instead: chart renders with every values file, structural tests (kinds, probes,
resources, PDBs, no host ports, policies, budgets), Compose config with every profile, rule
references, Redis lease logic with fakes (and the `TEST_REDIS_URL` lane when available), replica
routing and restore verification on PostgreSQL, tracing redaction with the in-memory exporter.

## 10. Deferred

- Default flips that wait for staging evidence, unchanged here: `RLS_ENFORCEMENT=strict` and
  `force_rls.sql`, `CELERY_QUEUE_TYPE=quorum`, `AGENT_RUN_EXECUTION=worker`, retrieval
  defaults from `0.6.0`, `REALTIME_EVENTS_ENABLED`, `APP_AUTH_SESSION_HINT_COOKIE_ENABLED`,
  `RUDIX_ROUTE_GATE=enforce`, Web Vitals, and removing `AUTH_LEGACY_SESSION_READ`.
- Frontend server tracing (needs a Next.js OpenTelemetry dependency, not approved).
- A self-hosted Postgres HA build (Patroni or similar); a vendor-specific Terraform module for
  cluster or managed services; a log shipper container.
- Neo4j online backup (Community edition); rotation of `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY`
  (needs re-encryption of stored credentials).
- API `--workers` above 1 (would need multiprocess metrics in the API).
- `R05-12` rich answer rendering (renderer not approved).

## 11. Status (2026-11-28)

All nine packages are merged into `develop`, in this order: S1 (chart skeleton, rule test,
settings stubs, shared gauges), C1 (workloads, autoscaling, network policy), B1 (Redis
WebSocket leases, shutdown drain, readiness scope, Redis roles), A1 (edge proxy, Compose
parity), D1 (secrets rotation, request-time frontend configuration, CDN), C2 (replica routing,
pooler, migration safety check), B2 (multiprocess worker metrics, SLO and burn-rate rules,
Alertmanager routing), A2 (backups, restore verification, runbooks), B3 (OpenTelemetry
tracing). No package is deferred or unmerged, and no `feat/v0.8.0-*` branch or worktree is
left. No migration was added: `alembic heads` reports one head, `20261128_0003`, so no
downgrade to the `0.7.0` head was needed.

Checked on `develop` plus the integration changes, with placeholder settings as in CI (no
`.env`) and the CI staging frontend values (no secrets):

- Backend: `make lint` passes (ruff; mypy on 970 files); `ruff format --check` passes;
  `make test` 7,225 passed, 44 skipped (run with `TEST_DATABASE_URL` set, so the Postgres
  tests ran too); `make test-cov` without `TEST_DATABASE_URL`, as in CI, 6,864 passed, 405
  skipped, coverage 83.01% (ratchet raised from 82.4 to 83.0).
- `make test-postgres`, run alone: 363 passed, 7 skipped in three of four runs; the fourth
  failed `test_keyset_plans_pg.py::test_documents_cursor_page_uses_index` (the planner chose a
  bitmap scan on another `documents` index). The test passes alone and is unchanged since
  `0.4.0`; it is a plan-stability flake, not a `0.8.0` change. Six skips need
  `TEST_REDIS_URL` (no Redis is available here, so the live lease and Lua script tests did not
  run); `tests/test_rls_enforcement_pg.py`, with `TEST_MIGRATIONS_DATABASE_URL`, passed 21 of
  21, including the migration round trip.
- `make check-revisions` passes; `check_migration_safety.py --all` passes on 103 files and
  `--base-ref main` on 9; the OpenAPI contract check passes (`frontend/openapi.json` matches).
- `deploy/scripts/check_helm_chart.sh` passes (lint, and render of the default, staging,
  production, `ci/all-features-values.yaml` and `ci/hpa-values.yaml` files);
  `check_compose_config.sh` and `check_observability_config.sh` pass.
- `make audit` fails on the dev-only `virtualenv` 21.14.5 (13 advisories, unchanged since
  `0.7.0`); the CI severity gate passes on the same report through its allowlist.
- Frontend: format, typecheck and lint pass (0 errors, 2 older warnings); Vitest 2,858 passed
  in 280 files, twice, with coverage 68.76% statements, 60.96% branches, 62.34-62.36%
  functions, 69.66% lines (ratchets raised from 68.6, 60.8, 62.1, 69.5 to 68.7, 60.9, 62.3,
  69.6); `api:check` and `api:check-handwritten` (72 modules) pass; `npm run build` passes,
  `check-prerendered-routes.mjs` finds all 144 static public routes, and
  `check-bundle-budgets.mjs` reports all 107 routes within budget; Playwright 416 passed
  (Chromium projects, including the route-gate and runtime-config projects).
- No setting is defined twice across the `Settings` bases (585 fields), no metric name is
  declared twice, and every `0.8.0` unchecked bullet in docs/11 ends with
  `(operator, 0.8.0)`. Every package has one `docs/CHANGELOG.md` entry; a stray blank line
  between C2 and A1 is removed and the D1 entry is labelled like the others. docs/README.md
  lists docs/28 and the runbooks once each.
- Docs that still described an earlier package state are updated: docs/28 status and scope,
  its docs/README.md entry, the docs/11 OTLP header rotation bullet (now names
  `OTEL_EXPORTER_OTLP_HEADERS`), the docs/12 backup gauge caveat (B2's multiprocess
  collection is merged), and the frontend README, which said the legacy session read is
  removed in `0.8.0` although section 10 defers it.

Not run here: `kubeconform`, `promtool check/test rules`, `amtool check-config`,
`caddy validate`, `terraform fmt/validate`, `shellcheck`, and `actionlint` (none is installed,
and the CI steps that run them start containers); the deploy-config job and the
`RUDIX_FRONTEND_IMAGE_MODE=single` release path first run in CI.

Open points from the package reviews, not fixed here:

- `rudix_beat_heartbeat_timestamp_seconds` and `rudix_db_replica_lag_seconds` have no labels
  and are exported as `0` by every process before anything sets them. `RudixBeatHeartbeatStale`
  uses `max()` and so also covers a beat that never ran, but `RudixBeatHeartbeatMissing`
  (`absent(...)`) cannot fire. The replica lag gauge keeps its last value while no report
  traffic samples it.
- `record_document_indexing_job` has no caller, so the indexing duration and job metrics,
  the ingestion SLO rules, and `RudixDocumentIndexingFailureRateHigh` return no data
  (older gap, documented in `slo_targets.yml` and docs/12).
- With tracing on, the httpx instrumentation sends `traceparent` to every outbound host
  (LLM providers, webhooks, connectors, email); docs/11 "Tracing" does not say so.
- `tests/test_usage_adoption_f353.py::test_http_onboarding_reminder_sent_and_404` sends real
  email when a developer's `.env` has a live email provider (reported during B3).
- Production deploys fail `check_deploy_env.sh` until `PRODUCTION_ENV_FILE` has a pinned
  `CADDY_IMAGE`, and production Matomo is not reachable until `EDGE_MATOMO=on`,
  `RUDIX_MATOMO_HOST`, and DNS are set (A1).

Still to verify on staging (section 9): only 80 and 443 reachable and the TLS scan; no failed
chat when a replica is killed under load; no lost work when a data-store node is lost; the
failover drill and a point-in-time restore checked by `verify_postgres_restore.py`; the first
restore drill with measured RPO and RTO in `docs/runbooks/RESTORE_DRILL_LOG.md` (empty); a
burst scaling out and back and a deploy under load with no failed requests; a synthetic alert
paging the on-call receiver; one end-to-end trace through a real collector; and the same image
digests on staging and production (needs the section 6 decisions). No latency, RPO, RTO,
failover, scan, or load figure is recorded in this release.

## 12. Change Notes

- 2026-11-28: Initial version, written after checking the `0.8.0` spec against the code at
  `9eb0acd3`, with the owner's instruction to take the recommended option on each open
  decision.
- 2026-11-28: Status after all nine packages merged (section 11): integration check
  results, raised coverage ratchets, doc fixes, open points, and staging checks.
