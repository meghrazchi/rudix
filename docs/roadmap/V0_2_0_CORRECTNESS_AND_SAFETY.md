# v0.2.0 — Correctness and Safety

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [00_AUDIT_BASELINE.md](./00_AUDIT_BASELINE.md)

## 1. Purpose

File-level steps, merge order, and the results of checking this spec against the code are in
[V0_2_0_IMPLEMENTATION_PLAN.md](./V0_2_0_IMPLEMENTATION_PLAN.md).

Fix defects that exist today. No refactoring beyond what each fix needs. Every item is small
enough to ship as its own merge request with a regression test.

## 2. Preconditions

Tag current `main` as `v0.1.0` (`R02-00`, size S).

## 3. Work items

### R02-01 — Chat transport parity (L)

- **Problem:** The WebSocket pipeline has no plan quota check, no usage recording, and no
  per-document citation authorization filter. The HTTP pipeline has all three.
- **Change:** Extract the three behaviours from `query_chat` into functions under
  `app/application/chat/` and call them from both pipelines. This is the first slice of the
  full unification in `R05-01`; do not attempt the full merge here.
- **Implementation:**
  - `ensure_chat_quota(session, principal)` wraps `plan_enforcement_service.ensure_within_limit`.
    Call it in `_run_ws_chat_pipeline` before retrieval. On denial, send the existing error
    event with the same code the HTTP path returns as 429.
  - `record_chat_usage(...)` wraps `record_usage`. Call it once after persistence.
  - `filter_citations_by_access(...)` holds the logic at `chat.py:3586-3613`. Replace the
    per-chunk document fetch with one `IN` query while moving it.
- **Done when:** A parity test runs the same question through HTTP and WebSocket and asserts
  the same quota denial, the same usage event count, and the same citation set for a user who
  lacks access to one cited document.

### R02-02 — Idempotent document processing claim (M)

- **Problem:** `documents.process` returns `skipped` when the status is `processing`, but the
  task itself sets `processing`. A retry or a redelivery after a worker crash therefore skips,
  and the document stays in `processing` forever.
- **Change:** Claim the document atomically and let the owning task re-enter.
- **Implementation:**
  - Migration (additive): `documents.processing_task_id` (text, null) and
    `documents.processing_started_at` (timestamptz, null).
  - Claim with one statement:
    `UPDATE documents SET status='processing', processing_task_id=:tid, processing_started_at=now()
    WHERE id=:id AND (status IN (<claimable>) OR processing_task_id=:tid
    OR processing_started_at < now() - :stale) RETURNING id`.
    Use the Celery root task ID so retries of the same task match.
  - Zero rows returned means another live task owns it: return `skipped`.
  - Add `documents.reap_stale` to the beat schedule. It re-queues documents whose
    `processing_started_at` is older than `DOCUMENT_PROCESSING_STALE_SECONDS`.
- **Done when:** Tests cover: retry after a transient error completes; redelivery with the
  same task ID completes; a second task with a different ID skips; the reaper re-queues a
  stale document exactly once. No duplicate chunks or vectors result.
- **Rollback:** Columns are nullable and unused by old code.

### R02-03 — Run Celery beat (S)

- **Problem:** `beat_schedule` is defined but no beat process is started anywhere, so
  connector polling and approval expiry never run.
- **Change:** Add a `beat` service to `docker-compose.yml` and the staging and production
  compose files, running `celery -A app.workers.celery_app beat`. Exactly one instance. Add
  `make run-beat` to `backend/Makefile`.
- **Done when:** The integration smoke in `release.yml` asserts a beat heartbeat metric or log
  line, and `backend/README.md` documents the process.

### R02-04 — Task registration and routing (S)

- **Problem:** `app.workers.safety_eval_tasks` is missing from the Celery `include` list.
  Four task names have no route and fall to `default`.
- **Change:** Add the module to `include`. Add explicit routes for `safety_evals.run`,
  `documents.graph_reindex`, `documents.backfill`, and `agents.approvals.expire`.
- **Done when:** A test imports every module under `app/workers`, collects task names, and
  asserts each is registered on the app and has an explicit route.

### R02-05 — Index version isolation (M)

- **Problem:** Production retrieval never filters on `index_version`. Evaluation chunking
  comparisons re-ingest documents under `eval-` versions into the same collection and table.
- **Verify first:** Query Qdrant and `document_chunks` in staging for `index_version` values
  starting with `eval-`.
- **Change:**
  - Pass the active `index_version` to the Qdrant filter and the FTS query on every
    production retrieval path, including the agent tool path.
  - Evaluation re-ingest deletes its points and chunk rows when the run finishes or fails.
    A separate Qdrant collection for evaluation vectors is deferred to `R06-12`.
  - One-off script `backend/scripts/purge_eval_index_versions.py` with a dry-run mode.
- **Done when:** An isolation test ingests the same document under a production and an eval
  version and asserts chat retrieval returns only production chunks.

### R02-06 — One session per concurrent branch (S)

- **Problem:** When a question is decomposed into two or more sub-queries, their keyword
  searches run concurrently on one `AsyncSession`. SQLAlchemy does not allow this, and the
  resulting errors are swallowed as branch failures. Graph expansion is not affected: it is
  awaited after the query `gather`.
- **Change:** Each keyword-search branch opens its own session from `SessionLocal`.
  Count swallowed branch failures in a metric `rudix_retrieval_branch_failures_total{branch}`
  and log them at warning level.
- **Done when:** A Postgres-marked test runs hybrid retrieval with three sub-queries and
  asserts zero branch failures.

### R02-07 — Atomic quota accounting (S)

- **Problem:** Quota usage is incremented with read-modify-write in Python.
- **Change:** Replace with `UPDATE ... SET used = used + :n WHERE ... RETURNING used`. Compare
  the returned value with the limit in the same call.
- **Done when:** A test fires 50 concurrent increments and the final value equals 50.

### R02-08 — Deployment defects (M)

- **Change:**
  - Make `infra_services` in `deploy/terraform/main.tf` a per-environment variable so
    production does not start `neo4j`.
  - `check_remote_backups.sh` and the duplicate inline check in `main.tf`: accept a directory, and fail when the newest file in it is
    older than `BACKUP_MAX_AGE_HOURS`.
  - Add volumes for RabbitMQ and Redis in production compose, and set a Redis password.
  - Pin `qdrant`, `minio`, and `rabbitmq` images to explicit versions.
  - Either add ClamAV to production compose or require `MALWARE_SCAN_ENABLED=false` to be set
    explicitly, and fail startup validation when scanning is enabled but the host is unset.
- **Done when:** `terraform validate` passes and the integration compose run starts every
  service the production variable list names.

### R02-09 — Security headers (M)

- **Change:** Add `headers()` to `frontend/next.config.ts` with HSTS, `X-Content-Type-Options`,
  `Referrer-Policy`, `frame-ancestors`, and a Content Security Policy. Ship the CSP as
  `Content-Security-Policy-Report-Only` first, then enforce in `0.3.0` once the report is
  clean. Add the same non-CSP headers to API responses with a small middleware.
- **Implementation:** The CSP must allow the consent-gated analytics hosts and the Google
  Fonts icon stylesheet until `R07-04` removes it. Use a nonce for the inline JSON-LD script.
- **Done when:** A Playwright test asserts the headers on a public page and an app page.

### R02-10 — WebSocket ticket authentication (M)

- **Problem:** The access token is sent as `?token=` and can reach proxy and access logs.
- **Change:** Add `POST /api/v1/chat/ws-ticket`, which returns a single-use ticket stored in
  Redis for 30 seconds and bound to user, organisation, and session. The client connects with
  `?ticket=`. Non-browser clients using API keys or service accounts authenticate with an
  `Authorization` header on the handshake. Keep `?token=` accepted behind `CHAT_WS_ALLOW_QUERY_TOKEN` (default true in
  `0.2.0`, false in `0.5.0`, removed in `1.0.0`).
- **Done when:** Tests cover ticket reuse rejection, expiry, and cross-organisation rejection.
  `docs/07_API_DESIGN.md` documents both modes and the deprecation.

### R02-11 — Reject dev auth fallback in production builds (S)

- **Change:** In the build-time validation in `next.config.ts`, fail the build when
  `NEXT_PUBLIC_AUTH_LOCAL_FALLBACK`, `_LOCAL_PASSWORD`, or `_DEFAULT_ACCESS_TOKEN` is set and
  the deployment environment is staging or production.
- **Done when:** A unit test of the validation function covers both environments.

### R02-12 — WebSocket rate limiter honours failure mode (S)

- **Change:** Use the configured fail-open or fail-closed mode in the WebSocket limiter, the
  same as the HTTP dependency.
- **Done when:** A test with Redis unavailable asserts both modes.

### R02-13 — Remove dead code (S)

- **Change:** Delete the seven stub service files that raise `NotImplementedError`, the
  `if (False and ...)` block in `document_tasks.py`, and the unused `RefreshTokenStore`. Mark
  the two legacy 501 routes `deprecated=True` in OpenAPI; remove them in `1.0.0`.
- **Done when:** `make lint && make test` pass and no import references remain.

### R02-14 — Documentation consistency (S)

- **Change:** Make `docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md`, `README.md`, and
  `docs/README.md` agree on what is implemented (a development overlay) and what is planned
  (staging and production rollout).

### R02-15 — Minimal Postgres test job (S)

- **Problem:** `R02-02`, `R02-06`, and `R02-07` fix concurrency defects that SQLite cannot
  reproduce, and the full Postgres lane is not due until `R03-01`.
- **Change:** Add a `pg_session` fixture and run `pytest -m "requires_postgres or
  requires_redis"` in the existing Alembic CI job, which already has both services.
- **Done when:** The concurrency tests for the three items above run in CI.

## 4. Exit criteria

- All items meet their "Done when" line.
- `make check-all` passes.
- Staging shows beat firing connector polls, and a document survives a forced worker kill
  during processing and reaches `indexed`.

## 5. Security Considerations

`R02-01`, `R02-05`, `R02-09`, `R02-10`, and `R02-11` are security fixes. Update
`docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` in the same merge requests. Keep exploit detail
out of public issue text.

## 6. Observability and Operations

New metrics: `rudix_retrieval_branch_failures_total`, `rudix_documents_reaped_total`,
`rudix_chat_quota_denied_total{transport}`. Add a beat heartbeat alert rule.

## 7. Change Notes

- 2026-11-26: Initial version.
- 2026-11-26: Corrected `R02-05`, `R02-06`, `R02-08`, and `R02-10` after a code check; added `R02-15`.
