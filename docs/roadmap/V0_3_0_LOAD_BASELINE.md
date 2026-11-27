# v0.3.0 — Load Test Baseline

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Not yet measured
- `Last Updated`: 2026-11-26
- `Related Docs`: [V0_3_0_IMPLEMENTATION_PLAN.md](./V0_3_0_IMPLEMENTATION_PLAN.md),
  [V0_3_0_TEST_AND_RELEASE_FOUNDATION.md](./V0_3_0_TEST_AND_RELEASE_FOUNDATION.md),
  [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../12_EVALUATION_AND_MONITORING.md](../12_EVALUATION_AND_MONITORING.md),
  [../../ci/load/README.md](../../ci/load/README.md)

## 1. Purpose

This is the first measured performance baseline for Rudix (`R03-09`). The targets in
`docs/26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md` section 4.6 are revised against it before
`0.4.0` starts.

**No measurements have been recorded yet.** The harness in `ci/load/` and the database metrics
it reads exist, but the harness has not been run against the integration stack. Every value
below reads "not yet measured" until someone runs it. Do not quote these tables as results
until the status above says `Measured`.

## 2. Environment

| Field | Value |
|---|---|
| Date of run | not yet measured |
| Git commit | not yet measured |
| Host (CPU, memory, OS) | not yet measured |
| Docker and Compose versions | not yet measured |
| Compose files | `docker-compose.integration.yml` + `docker-compose.integration-stub.yml` |
| API replicas and Uvicorn workers | not yet measured |
| Celery worker concurrency | not yet measured |
| DB pool size / max overflow (`rudix_db_pool_size`; the engine uses SQLAlchemy defaults) | not yet measured |
| LLM stub latency (`STUB_LLM_LATENCY_MS` / `STUB_LLM_LATENCY_JITTER_MS`) | not yet measured |
| `STUB_EMBEDDING_DIM` | not yet measured |
| Rate limits (`ENVIRONMENT`, `RATE_LIMIT_*`) | not yet measured |
| Documents indexed before the chat runs | not yet measured |
| Locust version | not yet measured |
| Load generator host | not yet measured |

## 3. Results

Latency columns are in milliseconds. Error rate is failures divided by requests. Queries per
request are bucket estimates from `rudix_db_queries_per_request`; `n/a (not HTTP)` marks
WebSocket and ingest timings, which are not HTTP requests. Max pool checked out is the highest
`rudix_db_pool_checked_out` sample during the run, for one API process.

### 3.1 `upload_ingest` (5 users, spawn rate 1, 10 minutes)

<!-- load-report:upload_ingest:start -->
| Request | Requests | p50 (ms) | p95 (ms) | Error rate | Queries/request p50 | Queries/request p95 | Max pool checked out |
|---|---|---|---|---|---|---|---|
| `POST /api/v1/documents/upload` | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |  |
| `GET /api/v1/documents/{document_id}/status` | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |  |
| `INGEST upload_to_indexed` | not yet measured | not yet measured | not yet measured | not yet measured | n/a (not HTTP) | n/a (not HTTP) |  |
| **All requests** | not yet measured | not yet measured | not yet measured | not yet measured |  |  | not yet measured |
<!-- load-report:upload_ingest:end -->

### 3.2 `documents_list` (50 users, spawn rate 10, 5 minutes)

<!-- load-report:documents_list:start -->
| Request | Requests | p50 (ms) | p95 (ms) | Error rate | Queries/request p50 | Queries/request p95 | Max pool checked out |
|---|---|---|---|---|---|---|---|
| `GET /api/v1/documents` | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |  |
| **All requests** | not yet measured | not yet measured | not yet measured | not yet measured |  |  | not yet measured |
<!-- load-report:documents_list:end -->

### 3.3 `admin_dashboard` (5 users, spawn rate 1, 5 minutes)

<!-- load-report:admin_dashboard:start -->
| Request | Requests | p50 (ms) | p95 (ms) | Error rate | Queries/request p50 | Queries/request p95 | Max pool checked out |
|---|---|---|---|---|---|---|---|
| `GET /api/v1/admin/usage/dashboard` | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |  |
| `GET /api/v1/admin/observability` | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |  |
| **All requests** | not yet measured | not yet measured | not yet measured | not yet measured |  |  | not yet measured |
<!-- load-report:admin_dashboard:end -->

### 3.4 `chat_http` (20 users, spawn rate 2, 10 minutes)

<!-- load-report:chat_http:start -->
| Request | Requests | p50 (ms) | p95 (ms) | Error rate | Queries/request p50 | Queries/request p95 | Max pool checked out |
|---|---|---|---|---|---|---|---|
| `POST /api/v1/chat` | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |  |
| **All requests** | not yet measured | not yet measured | not yet measured | not yet measured |  |  | not yet measured |
<!-- load-report:chat_http:end -->

### 3.5 `chat_ws` (50 users, spawn rate 5, 10 minutes)

<!-- load-report:chat_ws:start -->
| Request | Requests | p50 (ms) | p95 (ms) | Error rate | Queries/request p50 | Queries/request p95 | Max pool checked out |
|---|---|---|---|---|---|---|---|
| `POST /api/v1/chat/ws-ticket` | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured | not yet measured |  |
| `WS connect` | not yet measured | not yet measured | not yet measured | not yet measured | n/a (not HTTP) | n/a (not HTTP) |  |
| `WS time_to_first_event` | not yet measured | not yet measured | not yet measured | not yet measured | n/a (not HTTP) | n/a (not HTTP) |  |
| `WS full_answer` | not yet measured | not yet measured | not yet measured | not yet measured | n/a (not HTTP) | n/a (not HTTP) |  |
| **All requests** | not yet measured | not yet measured | not yet measured | not yet measured |  |  | not yet measured |
<!-- load-report:chat_ws:end -->

## 4. How to fill this in

1. Start the stack and seed the load user as described in
   [`ci/load/README.md`](../../ci/load/README.md) sections 1 and 2.
2. Run each scenario with the user count, spawn rate, and duration in its heading, while
   `ci/load/collect_metrics.py run` samples `/metrics` for the same duration.
3. Run `ci/load/report.py --update docs/roadmap/V0_3_0_LOAD_BASELINE.md` once per scenario. It
   replaces only the block between that scenario's `load-report` markers.
4. Fill in the environment table by hand from the machine and env file you used.
5. Set `Status` to `Measured` and update `Last Updated`.
6. Compare the numbers with `docs/26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md` section 4.6 and
   revise those targets in the same change, noting which numbers moved and why.

Only write numbers that the commands printed. If a scenario could not be run, leave its block
as "not yet measured" and say why in section 5.

## 5. Notes

- Not yet measured: no integration stack, LLM stub, or load generator host was available when
  this template was written.
- WebSocket handshakes and messages are not HTTP requests, so the middleware does not count
  their statements and the queries-per-request columns do not apply to `WS` rows.
