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

---

## Application Configuration

To enable metrics collection on the FastAPI API, configure your `.env`:

```env
METRICS_ENABLED=true
METRICS_PATH=/metrics
METRICS_REQUIRE_AUTH=false
WORKER_METRICS_ENABLED=true
WORKER_METRICS_PORT=9808
```

For full documentation and metrics reference, see [`docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md`](../../docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md).
