# Kubernetes Helm Deployment

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft (chart skeleton only; workloads arrive during `0.8.0`)
- `Last Updated`: 2026-11-28
- `Related Docs`: [10_DEPLOYMENT_DOCKER.md](./10_DEPLOYMENT_DOCKER.md),
  [11_SECURITY_AND_PRODUCTION_CHECKLIST.md](./11_SECURITY_AND_PRODUCTION_CHECKLIST.md),
  [12_EVALUATION_AND_MONITORING.md](./12_EVALUATION_AND_MONITORING.md),
  [14_GITHUB_ACTIONS_CI_CD_PIPELINE.md](./14_GITHUB_ACTIONS_CI_CD_PIPELINE.md),
  [roadmap/V0_8_0_IMPLEMENTATION_PLAN.md](./roadmap/V0_8_0_IMPLEMENTATION_PLAN.md),
  [roadmap/V0_8_0_PRODUCTION_INFRASTRUCTURE.md](./roadmap/V0_8_0_PRODUCTION_INFRASTRUCTURE.md)

## Purpose and scope

Rudix `0.8.0` adds a Helm chart, `deploy/helm/rudix/`, for running the frontend, API, MCP
server, Celery workers, and beat on Kubernetes (`R08-02`). Docker Compose
(`deploy/compose/*`, [docs/10](./10_DEPLOYMENT_DOCKER.md)) stays supported as the fallback.

In scope: the chart, its values files, the render and lint checks, and the structural tests.
Out of scope: provisioning a cluster, an ingress controller, cert-manager, KEDA, the
Prometheus Operator, managed data stores, a secret manager, or a CDN. Those are operator steps
(last section). No latency, failover, recovery, or load figure is recorded here; none can be
measured in the repository.

Status at `0.8.0` S1: the chart renders a config ConfigMap, a frontend ConfigMap, and a
ServiceAccount. Each later section is filled by the task named in its marker.

## Chart layout and conventions

```text
deploy/helm/rudix/
  Chart.yaml                  apiVersion v2, version 0.8.0, appVersion "0.8.0", kubeVersion >=1.27
  values.yaml                 every top-level key, each with a "# owner: <task>" comment
  values-staging.yaml         same keys as production; differs in scale, hosts, secret names
  values-production.yaml
  ci/all-features-values.yaml CI only: turns optional features on so every template renders
  templates/_helpers.tpl      shared helpers (S1 only; other tasks add templates/_<task>.tpl)
  templates/configmap.yaml           <fullname>-config from config.env
  templates/frontend-configmap.yaml  <fullname>-frontend from runtimeConfig.env
  templates/serviceaccount.yaml
  templates/NOTES.txt
```

**No data stores.** The chart deploys no PostgreSQL, Redis, RabbitMQ, Qdrant, object storage,
or Neo4j. It connects to stores the operator provides; their URLs and credentials go in the
existing Secret below.

**Secrets.** Values files never hold a secret value. `secrets.existingSecret` names a
Kubernetes Secret in the release namespace that the operator creates (or that an External
Secrets Operator syncs; see "Secrets and runtime configuration"). Every key in it becomes an
environment variable through `envFrom.secretRef`. `secrets.create` must stay `false`; the
chart fails to render otherwise. Placeholder names in the values files (`rudix-staging-app-env`,
`rudix-production-app-env`) are replaced by the operator.

**Non-secret configuration.** `config.env` holds non-secret backend environment
(`ENVIRONMENT`, `API_BASE_URL`, `FRONTEND_BASE_URL`, `LOG_FORMAT=json`, then one block per
task under a `# v080-<task>` comment). It renders into the `<fullname>-config` ConfigMap.
`config.env.ENVIRONMENT` must equal `global.environment`. Hosts use the reserved `.invalid`
TLD until the operator sets real ones. `runtimeConfig.env` (empty until D1) renders into the
`<fullname>-frontend` ConfigMap, which the frontend Deployment mounts with `envFrom`.

**Values ownership.** Each top-level key of `values.yaml` has one owner task (plan section
5.1): S1 `nameOverride`, `fullnameOverride`, `global`, `image`, `config`, `secrets`,
`serviceAccount`, `podSecurityContext`, `containerSecurityContext`, `tmpVolume`, `metrics`
(shape); A1 `ingress`; A2 `backup`, `dataStores`; B2 `metrics.workers`,
`metrics.serviceMonitor`; B3 `tracing`; C1 `frontend`, `api`, `mcp`, `workers`, `beat`,
`migrations`, `autoscaling`, `networkPolicy`, `podDisruptionBudget`, `rollout`,
`connectionBudget`; C2 `database`, `pgbouncer`; D1 `runtimeConfig`, `cdn`,
`secrets.externalSecret`. `values-staging.yaml` and `values-production.yaml` carry exactly the
same key paths, a subset of `values.yaml` (`R08-12`); a test enforces it.

**Helpers** (`templates/_helpers.tpl`, contract 5.2.2). Helpers that need a component take a
dict, for example `include "rudix.image" (dict "root" $ "component" "api")`.

| Helper | Argument | Renders |
|---|---|---|
| `rudix.fullname` | root | `<release>-rudix` (or `fullnameOverride`), at most 63 characters |
| `rudix.componentName` | dict | `<fullname>-<component>`; components `frontend`, `api`, `mcp`, `worker-<pool>`, `beat`, `migrate`, `pgbouncer`, `backup-<kind>`; any other name fails |
| `rudix.labels` | dict | `helm.sh/chart`, `app.kubernetes.io/{name,instance,component,version,managed-by,part-of}` |
| `rudix.selectorLabels` | dict | `app.kubernetes.io/{name,instance,component}` |
| `rudix.image` | dict | `<registry>/<repository>@sha256:<digest>` when the component digest is set, else `<registry>/<repository>:<tag>` (component tag, then `image.tag`, then the chart appVersion). `frontend` uses the frontend image; `api`, `mcp`, `migrate` the API image; `beat`, `worker-*`, `backup-*` the worker image |
| `rudix.envFrom` | root | `configMapRef` to `<fullname>-config`, plus `secretRef` to `secrets.existingSecret` when set |
| `rudix.podSecurityContext` | dict | `runAsNonRoot`, `runAsUser`/`runAsGroup`/`fsGroup` 10001 for backend images and 1000 (`node`) for the frontend, `seccompProfile: RuntimeDefault` |
| `rudix.containerSecurityContext` | root | `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `runAsNonRoot: true`, `capabilities.drop: [ALL]` |
| `rudix.tmpVolume`, `rudix.tmpVolumeMount` | root | an `emptyDir` named `tmp` (`tmpVolume.sizeLimit`) mounted at `/tmp` |
| `rudix.configMapName`, `rudix.frontendConfigMapName`, `rudix.serviceAccountName`, `rudix.imagePullSecrets` | root | names and pull secrets used by the templates |
| `rudix.envValue` | value | a quoted ConfigMap value; numbers stay plain digits, null becomes `""` |

Service ports by name (contract 5.2.2, used by C1): frontend `http` 3000, api `http` 8000,
mcp `http` 8010, workers `metrics` 9808.

**Render and lint.**

```bash
deploy/scripts/check_helm_chart.sh                      # lint + template every values file
RENDER_DIR=/tmp/helm deploy/scripts/check_helm_chart.sh # keep the rendered manifests
helm template rudix deploy/helm/rudix -f deploy/helm/rudix/values-staging.yaml
cd backend && .venv/bin/pytest -q tests/test_helm_chart_foundation.py
```

The script needs Helm 3 (`HELM_BIN` overrides the binary) and fails with a clear message when
it is missing. The chart tests skip with a reason when Helm is missing; CI installs Helm
`v3.19.0` in the `backend` job. `tests/helm_support.py` provides `render_chart(values_files,
set_values)` and the shared assertions every `tests/test_helm_chart_*.py` runs: standard labels
on every object; no `hostPort`, `hostNetwork`, `privileged: true`, `NodePort`, or
`LoadBalancer`; environment names matching `PASSWORD|SECRET|TOKEN|_KEY` only from a
`secretKeyRef` or `envFrom.secretRef`, never a literal or a ConfigMap (names ending in a
duration, switch, or count suffix such as `_SECONDS`, `_ENABLED`, `_TOKENS`, `_KEY_ID`, or
`_SITE_KEY` are not secrets; `NON_SECRET_ENV_NAME` lists them). ConfigMap values go through
`rudix.envValue`, which keeps numbers in plain digits (`52428800`, not `5.24288e+07`). The CI job
`deploy-config` also validates the rendered manifests with `kubeconform` (Kubernetes `1.30.0`
schemas); that step is first exercised in CI, not on a development machine.

## Edge and ingress

<!-- v080-A1 -->

## Data stores, backups, and restore

<!-- v080-A2 -->

## Stateless replicas and shutdown

<!-- v080-B1 -->

## Metrics and alerting

<!-- v080-B2 -->

## Tracing

<!-- v080-B3 -->

## Workloads, rollout, autoscaling, and network policy

<!-- v080-C1 -->

Added in `0.8.0` C1 (`R08-02`, `R08-07`, `R08-08`). Templates live under
`templates/{frontend,api,mcp,workers,beat,migrations,autoscaling,networkpolicy}/` with helpers
in `templates/_c1.tpl`. Every Service is `ClusterIP`; no pod uses a host port, host network,
or the API server token (`automountServiceAccountToken: false`). Ingress objects (A1) point at
the `<fullname>-frontend`, `<fullname>-api`, and `<fullname>-mcp` Services by port name `http`.

**Workloads.**

| Component | Kind | Command | Port | Default replicas | Grace |
|---|---|---|---|---|---|
| frontend | Deployment, Service, PDB | `node server.js` (`HOSTNAME=0.0.0.0`) | `http` 3000 | 2 | 30 s, preStop `sleep 5` |
| api | Deployment, Service, PDB | `uvicorn app.main:app --host 0.0.0.0 --port 8000` (one process per pod) | `http` 8000 | 2 | 60 s, preStop `sleep 10` |
| mcp (`mcp.enabled`, off) | Deployment, Service, PDB | `python -m app.mcp.main --transport streamable_http` | `http` 8010 | 2 | 30 s, preStop `sleep 5` |
| worker-`<pool>` | Deployment (+ Service `metrics` when `metrics.enabled`) | `python -m app.workers.pools <pool>` | `metrics` 9808 | 1 per pool | 120 s (acks_late) |
| beat | Deployment, `Recreate` | `celery ... beat --schedule /tmp/celerybeat-schedule` | none | exactly 1 | 10 s |
| migrate | Job (Helm hook) | see "Migrations before traffic" | none | one run | `activeDeadlineSeconds` 3600 |

The frontend gets `envFrom` the config ConfigMap, `secrets.existingSecret`, and the frontend
ConfigMap (`runtimeConfig.env`), plus a writable `emptyDir` at `/app/.next/cache` because the
root filesystem is read-only. Worker pools come from `workers.pools` (`ingest`, `graph`, `sync`,
`eval`, `default`, as `app/workers/pools.py`); the chart passes each pool's `queues` and
`concurrency` as `WORKER_POOL_<NAME>_QUEUES` and `WORKER_POOL_<NAME>_CONCURRENCY`, so the
chart is the one place that says what a pool consumes. The queue lists equal the pool
defaults; when you rename a `CELERY_QUEUE_*` queue, change the pool's `queues` too (a test
fails otherwise). Every container has requests and limits (from the Compose limits: api
2 CPU / 2Gi, workers 2 / 4Gi, frontend 1 / 1Gi, mcp 1 / 1Gi, beat 0.5 / 512Mi, with lower
requests); a pool's own `resources` replaces `workers.resources`.

**Probes.**

| Component | startup | readiness | liveness |
|---|---|---|---|
| api | `GET /api/v1/health` every 5 s, 24 failures | `GET /api/v1/ready` every 10 s | `GET /api/v1/health` every 15 s |
| frontend | `GET /robots.txt` | `GET /robots.txt` | `GET /robots.txt` |
| mcp | `GET /health` | `GET /health` | `GET /health` |
| worker-`<pool>` | exec `celery -A app.workers.celery_app:celery_app inspect ping -d <pool>@$HOSTNAME --timeout 10`, every 20 s, 15 failures | same, every 60 s, timeout 20 s | same, every 60 s, timeout 20 s |
| beat | none (B2 alerts on the heartbeat) | none | none |

The api readiness probe gates only on the stores every request needs:
`config.env.READINESS_REQUIRED_DEPENDENCIES=postgres,redis` (contract 5.2.6, setting from B1;
unset keeps today's "every dependency"). A Qdrant, object storage, RabbitMQ, or Neo4j blip
therefore never takes every API pod out of the Service at once. The frontend probes
`/robots.txt` because `/login` answers with a locale redirect and the proxy skips paths with a
file extension. The worker ping starts a Python process, so it runs rarely, as in Compose.

**Graceful shutdown (contract 5.2.5).** The api pod gets `UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN`
(`api.gracefulShutdownSeconds`, 30) and `API_SHUTDOWN_DRAIN_SECONDS` (`api.drainSeconds`, 15).
On termination the preStop `sleep` (10) lets endpoints and the ingress stop routing to the pod,
uvicorn then closes WebSockets with `1012` and finishes requests, and `lifespan` waits for
dropped runs before closing clients. The render fails when
`preStopSleepSeconds + gracefulShutdownSeconds + drainSeconds + 5 > terminationGracePeriodSeconds`
(defaults: 10 + 30 + 15 + 5 = 60), and when a frontend or mcp preStop is not below its grace
period.

**Zero-downtime rules (`R08-08`).**

- frontend, api, mcp: `RollingUpdate` with `maxUnavailable: 0` and `maxSurge: 25%`; worker
  pools `maxUnavailable: 0`, `maxSurge: 1`; `minReadySeconds` 10, `revisionHistoryLimit` 5,
  `progressDeadlineSeconds` 600 (`rollout.*`). A new pod must pass readiness before an old
  one stops.
- frontend and api spread across nodes: preferred pod anti-affinity plus a
  `topologySpreadConstraints` entry (`ScheduleAnyway`) on `rollout.topologyKey`.
- PodDisruptionBudgets (`podDisruptionBudget.enabled`, on) with `maxUnavailable: 1` for
  frontend, api, and mcp, so a node drain evicts one pod at a time.
- beat: `replicas: 1` always (any other value fails the render), `strategy: Recreate` so an
  old and a new beat never run together, no PDB, never autoscaled.
- Schema changes are expand-contract (C2, docs/CONTRIBUTING): the release being replaced must
  work on the migrated schema, because old pods serve until the new ones are ready.

**Migrations before traffic.** `templates/migrations/job.yaml` is a Helm hook
(`helm.sh/hook: pre-install,pre-upgrade`, `hook-delete-policy: before-hook-creation`,
`backoffLimit: 0`, `activeDeadlineSeconds: 3600`) that runs, in the order of
`deploy_compose_remote.sh`:

```sh
alembic upgrade head && python -m app.clients.qdrant_bootstrap && python scripts/run_graph_migrations.py
```

Helm waits for it and stops the release when it fails, so no new pod starts on an unmigrated
schema. Hooks run before the release's own objects exist, so the Job has its own hook
ConfigMap (`<fullname>-migrate`, the same data as `<fullname>-config`) and ServiceAccount,
created first (lower `helm.sh/hook-weight`). With `migrations.useMigrationUrl` (on in staging
and production) the Job's `DATABASE_URL` comes from the `DATABASE_MIGRATION_URL` key
(`migrations.migrationUrlSecretKey`) of `secrets.existingSecret`: the schema owner, not the
application role. The render fails when `useMigrationUrl` is set without `existingSecret`.

**Install and upgrade with image digests.** Deploy by digest, never by a moving tag. Resolve
the digests that passed staging (docs/14, `release.yml`), then:

```bash
api=$(docker buildx imagetools inspect "<registry>/api:vX.Y.Z" --format '{{json .Manifest.Digest}}' | tr -d '"')
worker=$(docker buildx imagetools inspect "<registry>/worker:vX.Y.Z" --format '{{json .Manifest.Digest}}' | tr -d '"')
frontend=$(docker buildx imagetools inspect "<registry>/frontend-production:<sha>" --format '{{json .Manifest.Digest}}' | tr -d '"')

helm template rudix deploy/helm/rudix --namespace rudix \
  -f deploy/helm/rudix/values-production.yaml \
  --set image.registry=<registry> \
  --set image.api.digest="$api" --set image.worker.digest="$worker" \
  --set image.frontend.repository=frontend-production --set image.frontend.digest="$frontend" > /tmp/rudix-production.yaml   # review first

helm upgrade --install rudix deploy/helm/rudix --namespace rudix --create-namespace \
  -f deploy/helm/rudix/values-production.yaml \
  --set image.registry=<registry> \
  --set image.api.digest="$api" --set image.worker.digest="$worker" \
  --set image.frontend.repository=frontend-production --set image.frontend.digest="$frontend" \
  --wait --timeout 20m
```

`<registry>` is the operator's registry; the chart's `registry.invalid/rudix` is a
placeholder. `--wait` makes Helm wait for the migrate hook and for every Deployment to become
ready; a failed hook or readiness timeout leaves the previous pods serving. Keep `--timeout`
above the migration's expected run time: a Helm timeout marks the release failed but does not
stop the Job (it runs until `migrations.activeDeadlineSeconds`, 3600 s), and re-running the
upgrade while it still runs deletes it (`before-hook-creation`) in the middle of a migration.
Check `kubectl get job <fullname>-migrate` before retrying.

**Rollback.** `helm history rudix -n rudix`, then `helm rollback rudix <revision> -n rudix
--wait`. A rollback runs no `pre-upgrade` hook, so it never runs migrations and never
downgrades the database; the earlier images run on the current schema, which expand-contract
keeps compatible. A schema downgrade is a manual, reviewed `alembic downgrade` step, never part
of a rollback. Compose deployments keep `deploy/scripts/rollback.sh`.

**Connection budget.** The chart computes the worst-case number of PostgreSQL connections the
release can open, during a rolling update, and writes it to the api Deployment annotation
`rudix.io/database-connections-worst-case`. With `connectionBudget.maxDatabaseConnections`
above 0 the render fails when the worst case exceeds it.

```text
per process = (DB_POOL_SIZE + DB_MAX_OVERFLOW) x enginesPerProcess        defaults (5 + 10) x 1
api         = (max replicas + surge) x per process
mcp         = (replicas + surge) x per process                            when mcp.enabled
workers     = sum over pools of (max replicas + 1 surge) x (concurrency + 1) x per process
beat        = 1 x per process
migrate     = 1                                                           alembic uses NullPool
```

- max replicas is `autoscaling.api.maxReplicas` (and each pool's `autoscaling.workers.pools.<pool>.maxReplicas`
  in keda mode) when autoscaling is on, otherwise the fixed replicas; surge is `maxSurge`
  rounded up (`25%` of 2 is 1).
- Each prefork child calls `engine.dispose(close=False)` after fork (`worker_process_init`)
  and builds its own `QueuePool`; the worker main process (dead-letter consumer, queue
  sampler) holds one too, hence `concurrency + 1`. Workers do not use `NullPool`.
- `enginesPerProcess` is 2 when `DATABASE_MAINTENANCE_URL` is set: the maintenance engine is
  a second pool in the same process.
- `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` are read from `config.env` (else
  `connectionBudget.defaultPoolSize` / `defaultMaxOverflow`).
- Surge counts the pods a rollout adds, not pods still terminating: a Deployment starts the
  next new pod as soon as an old one is told to stop, and that old pod keeps its pool for up
  to its grace period (api 60 s, workers 120 s). A rollout with several replicas per tier can
  briefly exceed the computed number; leave headroom below `max_connections` for it.

The defaults give 481 (api 45, workers 420, beat 15, migrate 1). Set
`maxDatabaseConnections` to the server's `max_connections` minus `superuser_reserved_connections`
and every other client (replication, backups, admin sessions). With a pooler (C2's PgBouncer in
transaction mode, or the provider's pooler) the application connects to the pooler: set the
budget to the pooler's client limit (`max_client_conn`); the server side is then bounded by the
pooler's `default_pool_size` per database and user, which you size against `max_connections`
separately. Lowering `DB_MAX_OVERFLOW` is the cheapest way to cut the worst case, because every
process holds its own pool.

**Autoscaling (`R08-07`).** `autoscaling.enabled` is off: fixed replicas. When on, the
Deployments it scales leave `replicas` unset so `helm upgrade` never resets the autoscaler.
The first upgrade that turns autoscaling on removes the field, so those Deployments drop to 1
replica until the autoscaler applies its minimum (seconds); do it outside peak traffic.

- `mode: keda` (KEDA installed by the operator; `autoscaling.prometheus.serverAddress` and
  `metrics.enabled` are required, or the render fails): ScaledObject for the api with Prometheus triggers on in-flight requests per
  replica (`sum(rudix_http_requests_in_progress{...})`, target 40) and open streams per
  replica (`sum(rudix_realtime_connections) + sum(rudix_chat_ws_connections)`, target 150,
  below the 200-streams-per-replica goal), plus CPU and memory; `minReplicaCount` 2 (a cold
  start never serves alone). A ScaledObject per worker pool on
  `max(rudix_celery_queue_depth{queue=~"<pool queues>"})` per replica and the p95 of
  `rudix_celery_queue_wait_seconds` (publish-to-start wait, the stand-in for the oldest message
  age; plan section 3); `minReplicaCount` 1 (a pool is never scaled to zero unless set). The
  frontend scales on CPU and memory. HPA behavior: scale up at most 100% per minute, scale down
  one pod per minute after a 300 s stabilization window.
- `mode: hpa`: `autoscaling/v2` HorizontalPodAutoscalers on CPU and memory for the api and the
  frontend; worker pools keep fixed replicas.
- Queries add `namespace="<release namespace>"`; set `autoscaling.prometheus.labelMatchers`
  when your scrape config labels the series differently. The queue metrics come from the
  default pool's sampler (`WORKER_SAMPLE_QUEUE_DEPTH`), so scrape the worker metrics port.
  Beat is never autoscaled.

**Network policy.** `networkPolicy.enabled` is on by default:

- `<fullname>-default-deny` selects every pod of the release and denies all ingress (and, with
  `networkPolicy.egress.enabled`, all egress).
- `<component>-from-ingress`: frontend, api, and mcp accept their `http` port only from the
  ingress controller namespace (`networkPolicy.ingressControllerNamespaceSelector`, default
  `kubernetes.io/metadata.name: ingress-nginx`; optional `ingressControllerPodSelector`). Set it
  to your controller's namespace before installing, or the site is unreachable.
- `api-from-frontend` (`networkPolicy.allowFrontendToApi`, off): only when the frontend proxies
  `/api/v1` to the in-cluster api Service (`NEXT_PUBLIC_PROXY_TARGET` at build time). Otherwise
  the browser reaches the API through the ingress.
- With `metrics.enabled`, the monitoring namespace (`networkPolicy.monitoringNamespaceSelector`,
  default `monitoring`) may reach the api `http` port and each worker's `metrics` port. The mcp
  server serves no `/metrics`, so its port stays closed to that namespace.
- `networkPolicy.dataStores` (empty by default: managed stores are outside the cluster): each
  entry (`name`, `podSelector`, `ports`, optional `namespace`) renders `datastore-<name>`, which
  allows ingress to those pods only from api, mcp, worker pools, beat, migrate, and `backup-*`
  pods of the release. The frontend never reaches a data store. A store in another namespace
  gets the policy in its namespace, with the release namespace required on the source.
- Egress restriction (`networkPolicy.egress.enabled`, off): pods may reach DNS
  (`dnsNamespaceSelector`, `kube-system`), each other, and `networkPolicy.egress.extraRules`
  (raw egress rules for the data stores, object storage, and model provider endpoints). Turn it
  on only after listing every external endpoint; a missing rule breaks that integration.
- A new component that needs ingress (C2's pooler, A2's backups if they serve anything) adds its
  own allow policy; the default deny covers it automatically.

**Checked here and staging-only.** `deploy/scripts/check_helm_chart.sh` renders every values
file (`ci/all-features-values.yaml` turns on mcp, keda, migration URL, data-store and egress
policies; `ci/hpa-values.yaml` covers hpa mode). `tests/test_helm_chart_workloads.py`,
`test_helm_chart_autoscaling.py`, and `test_helm_chart_networkpolicy.py` check kinds, probes,
resources, PDBs, the single beat, the hook Job, rolling updates without unavailability, the
grace and connection budgets (including the render failures), autoscaling objects, and the
policies. Not measurable here and left to staging (plan section 9): killing an api replica
during the load test, a burst scaling out and back, and a deploy under load with zero failed
requests.

## Database: managed Postgres, replica, pooler

<!-- v080-C2 -->

Added in `0.8.0` C2 (`R08-04`, `R08-08`). Helpers in `templates/_c2.tpl`; the pooler lives
under `templates/pgbouncer/`.

**Decision: managed PostgreSQL with point-in-time recovery** (plan section 2). The provider
runs the primary, the streaming replica, WAL archiving, PITR, and failover; the chart deploys no
database. Record the provider's RPO (the WAL archive interval) and failover behaviour in the
operator steps below. Restore verification is A2's `backend/scripts/verify_postgres_restore.py`
(contract 5.2.10): it checks the schema head, RLS policies, indexes, and row-count floors of a
restored instance; restore drills are logged in `docs/runbooks/RESTORE_DRILL_LOG.md`.

**Self-hosted fallback (documented, not built).** Without a managed provider: one primary and
one streaming replica (physical replication, `hot_standby = on`), continuous WAL archiving to
versioned object storage with a WAL archiving and base backup tool (the pgBackRest or WAL-G
class), and a failover manager (the Patroni class) or a documented manual promotion. The
local and Compose `postgres` service stays a single instance; nothing in this repository
provisions the fallback.

**Connection strings come only from the Secret.** `database.secretKeys` names the keys of
`secrets.existingSecret`; values never appear in a values file or ConfigMap:

| Key | Role | Used by |
|---|---|---|
| `DATABASE_URL` | application role (`rudix_app`, no `BYPASSRLS`); the PgBouncer Service when the pooler is on | api, mcp, workers, beat |
| `DATABASE_REPLICA_URL` | read-only role on the replica (optional) | api reporting routes only |
| `DATABASE_MIGRATION_URL` | schema owner, direct (never through the pooler) | migrate Job (`migrations.useMigrationUrl`) |
| `DATABASE_MAINTENANCE_URL` | `BYPASSRLS` maintenance role (optional) | beat cross-tenant tasks |

**Read replica for reports.** With `DATABASE_REPLICA_URL` unset everything stays on the
primary (the behaviour before 0.8.0). When set, `get_reporting_db_session` (contract 5.2.11)
gives these routes a read-only replica session and nothing else:

- `GET /api/v1/admin/usage/dashboard` (F153)
- `GET /api/v1/admin/usage-adoption/summary`, `/charts`, `/funnel`, `/users`, `/export` (F353)
- `GET /api/v1/reports`, `GET /api/v1/reports/answer-quality`

`POST /reports/events`, the onboarding-reminder POST, the per-message answer-quality detail,
authentication and authorization lookups, and every other route stay on the primary, so a
request that reads its own writes never sees a stale replica.

- *Staleness.* The lag is sampled on demand: when a reporting session is requested and the last
  sample is older than `DB_REPLICA_LAG_CHECK_INTERVAL_SECONDS` (10), one query runs on the
  replica (`pg_last_xact_replay_timestamp()`, 0 when the replica has replayed everything it
  received, 0 on a primary) with `DB_REPLICA_LAG_QUERY_TIMEOUT_MS` (500) covering checkout and
  query. The route uses the replica only while the fresh sample is at most
  `DB_REPLICA_MAX_LAG_SECONDS` (30); a failed, timed-out, or stale sample, or a larger lag,
  sends it to the primary until the next sample. Reports can therefore be up to the limit plus
  one interval behind.
- *Read-only.* The replica engine sets `default_transaction_read_only=on` on its connections;
  in PgBouncer mode (`DB_PGBOUNCER_MODE=true`, startup parameters ignored) every replica
  transaction runs `SET TRANSACTION READ ONLY` instead. Use a read-only database role anyway.
- *Tenant.* The replica session is bound to the same organization as the request's primary
  session and runs the same RLS session-context statement (`app.current_organization_id`,
  `app.rls_mode`), so strict RLS applies on the replica too; `set_config` works on a hot
  standby.
- *Pool.* `DB_REPLICA_POOL_SIZE` and `DB_REPLICA_MAX_OVERFLOW` (5 and 10) per api process;
  the engine is built on first use, so workers never open it.
- *Metrics and alerts.* `rudix_db_replica_lag_seconds` (last sample) and
  `rudix_db_replica_routed_total{target,reason}` (`reason`: `ok`, `replica_unset`,
  `lag_exceeded`, `sample_failed`). `infra/observability/prometheus/rules/database.yml`:
  `RudixDbReplicaLagHigh` (lag above 30 s for 5 m) and `RudixDbReplicaFallbacks` (fallbacks
  for 15 m), both `warning`.
- *Failover.* When the provider promotes the replica, the old replica URL stops answering or
  points at the new primary: samples fail (fallback to the primary, alert after 15 m) or read 0
  (`pg_is_in_recovery()` false). Point `DATABASE_URL` at the new primary through the
  provider's endpoint, and `DATABASE_REPLICA_URL` at the new replica when one exists, then roll
  the api. A replica outage never fails a report request.

**Pooler (`pgbouncer.enabled`, off).** PgBouncer in transaction mode between the application
pods and PostgreSQL, or the managed provider's pooler instead (then leave `pgbouncer.enabled`
off and set only the mode).

- `database.pgbouncerMode` must equal `config.env.DB_PGBOUNCER_MODE` (render failure
  otherwise); `pgbouncer.enabled` requires both true, `migrations.useMigrationUrl` (migrations
  connect directly), `pgbouncer.image` (no default image is guessed; pin a digest), and
  `pgbouncer.configSecretName`: an existing Secret with `pgbouncer.ini` (`pool_mode =
  transaction`, `listen_port` = `pgbouncer.port`, no `logfile` or `pidfile`) and
  `userlist.txt` or `auth_query` settings, mounted read-only at `/etc/pgbouncer`.
- Renders a Deployment (`pgbouncer.replicas`, 2; rolling update with `maxUnavailable: 0`;
  non-root, read-only root filesystem, `/tmp` writable; TCP readiness and liveness on port
  `postgres`), a ClusterIP Service `<fullname>-pgbouncer:6432`, a PDB when replicas > 1, and a
  NetworkPolicy that accepts the port only from api, mcp, worker pools, beat, migrate, and
  `backup-*` pods. The pooler joins the clients of every `networkPolicy.dataStores` policy so
  it can reach an in-cluster PostgreSQL. Point `DATABASE_URL` in the Secret at the Service.
- Connection budget: without the pooler C1's worst case counts application connections. With
  it, `rudix.io/database-connections-worst-case` on the api Deployment becomes the pooler's
  server side, `(replicas + surge) x (defaultPoolSize + reservePoolSize) + 1` (migrate), and
  `connectionBudget.maxDatabaseConnections` applies to that. The application side (C1's
  formula) is written to `rudix.io/pooler-client-connections-worst-case` on the pooler and the
  render fails when it exceeds `pgbouncer.replicas x pgbouncer.maxClientConnections`. Keep
  `defaultPoolSize`, `reservePoolSize`, and `maxClientConnections` equal to `pgbouncer.ini`.

**Migration safety (`R08-08`).** `backend/scripts/check_migration_safety.py` runs in the CI
job `backend-alembic` (`--all`, and `--base-ref origin/<base>` on pull requests) and locally
with `make check-migration-safety`. The expand-contract policy, the rules, the override marker,
and the allowlist are in `docs/CONTRIBUTING.md`, "Database migrations". The migrate Job runs
before traffic (pre-install and pre-upgrade hook, C1); a failed migration stops the release and
nothing downgrades automatically.

**Checked here and staging-only.** `tests/test_helm_chart_database.py` renders the pooler and
the failures; `tests/test_db_replica_routing.py` covers the routing decisions;
`tests/test_db_replica_pg.py` (Postgres lane, `TEST_DATABASE_URL` as the replica) proves
read-only sessions in both modes, the tenant binding under strict RLS, and identical report
bodies through the replica and the primary. A failover drill and a point-in-time restore
against a real scratch instance are staging-only (plan section 9).

## Secrets and runtime configuration

<!-- v080-D1 -->

## Operator steps

Not done in the repository (plan section 8):

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
   (plan section 6) before enabling the single frontend image.
10. Run the load test at target scale, kill one replica of each tier, deploy under load, run
    the failover drill and the first restore drill, and record RPO and RTO in
    `docs/runbooks/RESTORE_DRILL_LOG.md`.

## Change Notes

- 2026-11-28: Initial version (`0.8.0` S1): chart layout, conventions, helpers, render and lint
  checks; empty sections for A1, A2, B1, B2, B3, C1, C2, and D1.
- 2026-11-28: `0.8.0` C1: workloads, probes, shutdown and connection budgets, migrate hook Job,
  rollout rules, KEDA and HPA autoscaling, network policies.
- 2026-11-28: `0.8.0` C2: database Secret keys, read replica for reporting routes with lag
  sampling and fallback, optional PgBouncer Deployment and pooler-aware connection budget,
  migration safety check.
