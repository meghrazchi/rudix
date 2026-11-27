# Rudix load-test harness (R03-09)

Locust scenarios for the API, a `/metrics` scraper for database usage, and a report generator
that fills [`docs/roadmap/V0_3_0_LOAD_BASELINE.md`](../../docs/roadmap/V0_3_0_LOAD_BASELINE.md).

> **Status: not yet run.** The harness was written and unit-tested, but it has not yet been
> run against a full stack, so the baseline document holds no measurements.

## Layout

| Path | Purpose |
|---|---|
| `locustfile.py` | Entry point; imports the five user classes and applies `RUDIX_LOAD_SCENARIO_WEIGHTS`. |
| `common/config.py` | Reads settings from the environment (see below). |
| `common/auth.py` | `POST /api/v1/auth/login`, refresh through `POST /api/v1/auth/token/refresh`, re-login fallback. |
| `common/events.py` | Custom Locust request events for WebSocket and ingest timings. |
| `scenarios/chat_ws.py` | `ChatWsUser`: ticket, WebSocket connect, `chat.start`, time to first event and full answer (`WS` request type). |
| `scenarios/chat_http.py` | `ChatHttpUser`: `POST /api/v1/chat`. |
| `scenarios/documents_list.py` | `DocumentsListUser`: `GET /api/v1/documents` with `limit`/`offset` pagination. |
| `scenarios/upload_ingest.py` | `UploadIngestUser`: upload a generated TXT, poll `/status` until `indexed` (`INGEST upload_to_indexed`). |
| `scenarios/admin_dashboard.py` | `AdminDashboardUser`: `GET /api/v1/admin/usage/dashboard` and `GET /api/v1/admin/observability`. |
| `collect_metrics.py` | Standard library. Scrapes `/metrics` before and after a run, samples the pool gauge, writes JSON. |
| `report.py` | Standard library. Merges Locust `--csv` stats and the metrics JSON into the baseline tables. |

The unit tests for `collect_metrics.py`, `report.py`, and `common/config.py` are in
`backend/tests/test_load_harness_tools.py`. The Locust import test there runs only when Locust
is installed.

## Prerequisites

- Docker with Compose v2, and the API and worker images built locally. Example (no push):
  `docker build -t rudix-local-api:load backend` and the worker image built the same way as the
  `build-images` job in `.github/workflows/release.yml`.
- The LLM stub overlay `deploy/compose/docker-compose.integration-stub.yml` and
  `ci/stubs/llm_stub.py` (owned by R03-04). They replace OpenAI with a deterministic local
  service, so a load run costs nothing and its latency is set by you.
- Locust, through the dev-only `load` extra (never installed into an image):

  ```bash
  make -C backend install-load
  ```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `RUDIX_LOAD_BASE_URL` | `http://localhost:8000` | API origin. WebSocket URLs are derived from it (`ws://` or `wss://`). |
| `RUDIX_LOAD_EMAIL` | none (required) | The seeded load-test account. |
| `RUDIX_LOAD_PASSWORD` | none (required) | Its password. Never logged. |
| `RUDIX_LOAD_ORG_ID` | none | Optional `X-Organization-ID` header. |
| `RUDIX_LOAD_SCENARIO_WEIGHTS` | `chat_ws=3,chat_http=1,documents_list=4,upload_ingest=1,admin_dashboard=1` | Weights for a mixed run. `0` removes a scenario. |
| `RUDIX_LOAD_QUESTIONS_FILE` | built-in list | One question per line; `#` lines are skipped. |
| `RUDIX_LOAD_INGEST_TIMEOUT_SECONDS` | `300` | Upload-to-terminal timeout for `upload_ingest`. |
| `RUDIX_LOAD_WS_TIMEOUT_SECONDS` | `120` | Timeout for `connection.ready` and for `chat.completed`. |
| `RUDIX_LOAD_METRICS_TOKEN` | none | Bearer token for `/metrics` when `METRICS_REQUIRE_AUTH=true`. |

## 1. Start the stack

1. Create `.env.ci.integration` in the repository root with the same content as the
   `Create integration env file` step of the `integration-smoke` job in
   `.github/workflows/release.yml`. Set `RUDIX_API_IMAGE` and `RUDIX_WORKER_IMAGE` to your
   local tags. Keep `METRICS_ENABLED=true`; `METRICS_DB_QUERY_COUNTING_ENABLED` defaults to
   `true`.
2. Choose the artificial LLM latency. The stub reads `STUB_LLM_LATENCY_MS` (default `0`) and
   `STUB_LLM_LATENCY_JITTER_MS` (default `0`) per completion, and `STUB_EMBEDDING_DIM`
   (default `1536`, must match `QDRANT_VECTOR_SIZE`). The baseline uses 800 ms with 200 ms
   jitter so chat numbers include a realistic model wait:

   ```bash
   export STUB_LLM_LATENCY_MS=800 STUB_LLM_LATENCY_JITTER_MS=200
   ```

3. Start the stack, migrate, and seed the load user:

   ```bash
   export BOOTSTRAP_ADMIN_EMAIL=load-admin@example.test BOOTSTRAP_ADMIN_PASSWORD='<choose one>'
   make load-stack-up
   ```

   This is the same as:

   ```bash
   docker compose -f deploy/compose/docker-compose.integration.yml \
     -f deploy/compose/docker-compose.integration-stub.yml \
     --env-file .env.ci.integration up -d
   docker compose -f deploy/compose/docker-compose.integration.yml \
     -f deploy/compose/docker-compose.integration-stub.yml \
     --env-file .env.ci.integration run --rm migrate
   docker compose -f deploy/compose/docker-compose.integration.yml \
     -f deploy/compose/docker-compose.integration-stub.yml \
     --env-file .env.ci.integration run --rm \
     -e BOOTSTRAP_ADMIN_EMAIL -e BOOTSTRAP_ADMIN_PASSWORD api python scripts/bootstrap_admin.py
   ```

   `bootstrap_admin.py` creates an owner only when the database has no organization, so the
   bootstrap admin is the load user (owners can call the admin dashboard routes).

4. Point the harness at it:

   ```bash
   export RUDIX_LOAD_BASE_URL=http://localhost:8000
   export RUDIX_LOAD_EMAIL="$BOOTSTRAP_ADMIN_EMAIL" RUDIX_LOAD_PASSWORD="$BOOTSTRAP_ADMIN_PASSWORD"
   ```

With `ENVIRONMENT=test`, request rate limits are disabled (`RATE_LIMIT_DISABLE_IN_TEST`), so the
numbers measure capacity rather than limits. Record that in the baseline environment block.

Stop and remove the stack (volumes included) with `make load-stack-down`.

## 2. Run the scenarios

Run `upload_ingest` first so the chat scenarios retrieve from indexed documents. Each run
writes `ci/load/results/<scenario>_stats.csv` (ignored by git). Start
`collect_metrics.py run` in a second terminal at the same moment, with `--duration` equal to
the Locust run time, or use `make load-test`, which does both.

| Scenario | Users (`-u`) | Spawn rate (`-r`) | Duration (`-t`) |
|---|---|---|---|
| `upload_ingest` | 5 | 1 | 10m |
| `documents_list` | 50 | 10 | 5m |
| `admin_dashboard` | 5 | 1 | 5m |
| `chat_http` | 20 | 2 | 10m |
| `chat_ws` | 50 | 5 | 10m |

```bash
L="backend/.venv/bin/locust -f ci/load/locustfile.py --headless --only-summary"
M="python3 ci/load/collect_metrics.py run $RUDIX_LOAD_BASE_URL/metrics"
mkdir -p ci/load/results

$M --duration 600 --out ci/load/results/upload_ingest_metrics.json &
$L -u 5 -r 1 -t 10m --csv ci/load/results/upload_ingest UploadIngestUser; wait

$M --duration 300 --out ci/load/results/documents_list_metrics.json &
$L -u 50 -r 10 -t 5m --csv ci/load/results/documents_list DocumentsListUser; wait

$M --duration 300 --out ci/load/results/admin_dashboard_metrics.json &
$L -u 5 -r 1 -t 5m --csv ci/load/results/admin_dashboard AdminDashboardUser; wait

$M --duration 600 --out ci/load/results/chat_http_metrics.json &
$L -u 20 -r 2 -t 10m --csv ci/load/results/chat_http ChatHttpUser; wait

$M --duration 600 --out ci/load/results/chat_ws_metrics.json &
$L -u 50 -r 5 -t 10m --csv ci/load/results/chat_ws ChatWsUser; wait
```

The equivalent Make call for one scenario:

```bash
make load-test LOAD_SCENARIO=chat_ws LOAD_USERS=50 LOAD_SPAWN_RATE=5 LOAD_DURATION_SECONDS=600
```

`make load-test` skips with a message when Locust is not installed or the API does not answer
`/api/v1/health`. Locust exits non-zero when any request failed; the report is still written.

What each scenario records:

- `chat_ws`: `POST /api/v1/chat/ws-ticket`, `WS connect` (handshake until `connection.ready`),
  `WS time_to_first_event` (first non-heartbeat event after `chat.start`), and
  `WS full_answer` (until `chat.completed`). `chat.error`, `chat.cancelled`, timeouts, and
  rejected handshakes are failures whose message is a safe code only.
- `upload_ingest`: `POST /api/v1/documents/upload`, the status polls, and
  `INGEST upload_to_indexed`. Any other terminal status, or the timeout, is a failure.
- The others record one Locust row per route template.

## 3. Produce the report

```bash
for s in upload_ingest documents_list admin_dashboard chat_http chat_ws; do
  python3 ci/load/report.py --scenario "$s" \
    --stats "ci/load/results/${s}_stats.csv" \
    --metrics "ci/load/results/${s}_metrics.json" \
    --update docs/roadmap/V0_3_0_LOAD_BASELINE.md
done
```

`report.py` replaces only the block between `<!-- load-report:<scenario>:start -->` and
`<!-- load-report:<scenario>:end -->`. Without `--update` it prints the table. Then fill in the
environment block by hand, set the document status to `Measured`, and revise the targets in
`docs/26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md` section 4.6 against the numbers.

`collect_metrics.py` can also work offline:

```bash
python3 ci/load/collect_metrics.py snapshot http://localhost:8000/metrics --out before.prom
# ... run Locust ...
python3 ci/load/collect_metrics.py snapshot http://localhost:8000/metrics --out after.prom
python3 ci/load/collect_metrics.py diff --before before.prom --after after.prom --out m.json
```

Queries-per-request quantiles come from the `rudix_db_queries_per_request` histogram buckets
(1, 2, 5, 10, 20, 50, 100, 200) with Prometheus-style interpolation, so they are estimates.
The pool maximum is the highest `rudix_db_pool_checked_out` value seen across the samples
(every `--interval` seconds, default 2), so short spikes between samples can be missed. Both
are per API process: with several Uvicorn workers or replicas, scrape each one.

## Safety

- Use a disposable stack and a dedicated account. The scenarios upload documents and create
  chat sessions.
- Do not point the harness at production.
- The harness never logs tokens, tickets, passwords, or response bodies; failure messages hold
  status codes or safe error codes only.
