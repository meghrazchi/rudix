# Rudix Prometheus & Grafana Observability Stack

This directory contains the self-hosted **Prometheus**, **Alertmanager**, and **Grafana** observability stack for Rudix.

---

## Architecture Overview

```
                      ┌────────────────┐
                      │  Grafana UI    │
                      │  (:3001)       │
                      └───────┬────────┘
                              │ PromQL
                      ┌───────▼────────┐      Alerts     ┌──────────────┐
                      │  Prometheus    ├────────────────►│ Alertmanager │
                      │  (:9090)       │                 │ (:9093)      │
                      └───────┬────────┘                 └──────────────┘
                              │
     ┌──────────────┬─────────┴────────┬─────────────┬─────────────┐
     ▼              ▼                  ▼             ▼             ▼
API (:8000)   Worker (:9808)    Qdrant (:6333)  Postgres      Redis
/metrics      /metrics          /metrics        (:9187)       (:9121)
```

---

## Quick Start

### 1. Start with Rudix

From the repository root:

```bash
make up-observability
```

Or using Docker Compose:

```bash
docker compose -f docker-compose.yml -f infra/observability/docker-compose.yml up -d
```

### 2. Access the Interfaces

| Service | URL | Credentials / Notes |
|---|---|---|
| Grafana | `http://localhost:3001` | Default: `admin` / `change-me-in-production` (configured via `GRAFANA_ADMIN_PASSWORD`) |
| Prometheus | `http://localhost:9090` | Time-series database, targets, and PromQL explorer |
| Alertmanager | `http://localhost:9093` | Alert routing and silence management |

### 3. Stop the Observability Stack

```bash
make down-observability
```

---

## Pre-provisioned Grafana Dashboards

The stack automatically provisions five dashboards in the `Rudix` folder:

1. **`01 — Rudix Executive & SLO Overview`**: Availability, Chat p95 latency, indexing success rate, worker failure rate, dependency readiness.
2. **`02 — Rudix RAG & LLM Performance`**: RAG stage latency waterfall, confidence distribution, grounded vs not-found ratio, token throughput, and estimated USD spend.
3. **`03 — Rudix Document Ingestion & Celery Workers`**: RabbitMQ queue depth, Celery task throughput & retries, and document ingestion duration.
4. **`04 — Rudix Data Stores & Infrastructure`**: PostgreSQL active connection pool, Qdrant vectors, Redis memory, and MinIO storage usage.
5. **`05 — Rudix Security, Governance & Tool Guardrails`**: Rate-limit rejections, auth verification failures, cross-tenant boundary denials, and agent tool execution.
6. **`07 — Rudix Worker Pools & Queues`** (0.6.0, R06-03..05): queue depth and consumers per queue, queue wait p50/p95, dead-letter queue depth and consumer outcomes, and task time-limit kills. Alert group `rudix-workers` in `prometheus/alerts.yml`.

---

## Configuration Defaults & Setup Reference

The entire observability stack is designed with built-in fallback defaults for zero-configuration local development.

### 1. Default Values Matrix

| Component | Setting | Default Value | When to Override |
|---|---|---|---|
| **API** | `METRICS_ENABLED` | `false` | Set to `true` to enable metrics scraping on the API. |
| | `METRICS_PATH` | `/metrics` | Change only if serving behind custom subpaths. |
| | `METRICS_REQUIRE_AUTH` | `false` | Set `true` in production if `/metrics` is exposed across networks. |
| | `METRICS_BEARER_TOKEN` | `None` / empty | Provide secret token when `METRICS_REQUIRE_AUTH=true`. |
| **Worker** | `WORKER_METRICS_ENABLED` | `false` | Set to `true` to scrape Celery worker task metrics. |
| | `WORKER_METRICS_PORT` | `9808` | Host/container port for worker metrics HTTP listener. |
| **Prometheus** | `PROMETHEUS_PORT` | `9090` | Change if port 9090 conflicts on your host. |
| | `PROMETHEUS_RETENTION_TIME` | `15d` | Increase to `30d` or `90d` for long-term retention. |
| | `PROMETHEUS_RETENTION_SIZE` | `10GB` | Storage volume cap before oldest metrics are purged. |
| **Alertmanager** | `ALERTMANAGER_PORT` | `9093` | Host port for Alertmanager UI and API. |
| **Grafana** | `GRAFANA_PORT` | `3001` | Host port for Grafana web dashboard. |
| | `GRAFANA_ADMIN_USER` | `admin` | Initial administrator username. |
| | `GRAFANA_ADMIN_PASSWORD` | `change-me-in-production` | **Must override** in non-local environments. |
| **Exporters** | `POSTGRES_USER` | `postgres` | Matches default local PostgreSQL user. |
| | `POSTGRES_PASSWORD` | `postgres` | Matches default local PostgreSQL password. |
| | `POSTGRES_DB` | `rag_app` | Matches default local database name. |
| | `REDIS_ADDR` | `redis://redis:6379` | Matches default local Redis service name. |

### 2. Zero-Config Local Setup

To run locally with all defaults:

1. Enable metrics in your root `.env`:
   ```env
   METRICS_ENABLED=true
   WORKER_METRICS_ENABLED=true
   ```
2. Launch the stack:
   ```bash
   make up-observability
   ```
3. Open Grafana at `http://localhost:3001` with `admin` / `change-me-in-production`. All 5 dashboards are ready with data sources connected.

### 3. Production Hardening Checklist

When deploying to Staging or Production:
- Set a strong secret `GRAFANA_ADMIN_PASSWORD`.
- If `/metrics` is exposed across host or VPC boundaries, enable authentication:
  ```env
  METRICS_REQUIRE_AUTH=true
  METRICS_BEARER_TOKEN=<generate-strong-32-char-token>
  ```
- Configure Alertmanager notifications in `infra/observability/alertmanager/alertmanager.yml` (e.g. Slack webhook or PagerDuty key).

---

## CI/CD Pipeline Integration

Observability configs are verified in GitHub Actions:
- **`ci.yml`**: Validates Grafana dashboard JSON schema integrity and ensures `.env.example` contains required metrics flags.
- **`release.yml`**: Spins up the integration stack with `METRICS_ENABLED=true` and verifies the `/metrics` endpoint returns expected Prometheus series (`rudix_http_requests_total`).

For full architectural details and metrics reference, see [`docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md`](../../docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md).
