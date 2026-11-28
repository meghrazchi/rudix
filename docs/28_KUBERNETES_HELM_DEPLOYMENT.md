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
`secretKeyRef` or `envFrom.secretRef`, never a literal or a ConfigMap. The CI job
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

## Database: managed Postgres, replica, pooler

<!-- v080-C2 -->

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
