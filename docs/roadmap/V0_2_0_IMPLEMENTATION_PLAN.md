# v0.2.0 — Detailed Implementation Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [V0_2_0_CORRECTNESS_AND_SAFETY.md](./V0_2_0_CORRECTNESS_AND_SAFETY.md),
  [00_AUDIT_BASELINE.md](./00_AUDIT_BASELINE.md),
  [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md)

## 1. Purpose

Turn the `0.2.0` spec into merge-request-sized steps with the exact files, functions,
migrations, and tests. Every code reference below was read at commit `219b648c`. Line numbers
drift; search for the quoted symbol if a line does not match.

Detailed plans for `0.3.0` and later are written when the preceding version lands. Those
versions rewrite the files they would reference (`0.5.0` replaces `chat.py`, `0.6.0` replaces
`document_tasks.py`), so line-level plans written now would be wrong by the time they are used.

## 2. Plan check: what the code review changed

The spec was checked against the code before this plan was written. Results:

| Item | Result |
|---|---|
| R02-01 | Confirmed. WebSocket records a usage event (`chat.py:7158`) but never calls `plan_enforcement_service`, and has no `Action.cite` filter. |
| R02-02 | Confirmed. `documents.process` skips on `processing` (`document_tasks.py:3061`) and nothing resets the status before an autoretry. |
| R02-03 | Confirmed. No `beat` in any compose file or Makefile. |
| R02-04 | Confirmed. `safety_eval_tasks` is imported only by `interfaces/http/safety_evals.py:33`. |
| R02-05 | Confirmed by reading. Chat never passes `index_version`; keyword search has no `index_version` filter; evaluation re-ingest has no cleanup. Still needs the staging data check. |
| R02-06 | **Narrowed.** The shared session is used concurrently only when two or more sub-queries run keyword search. Graph expansion is created as a coroutine and awaited after the query `gather`, so it is sequential, not concurrent. |
| R02-07 | Confirmed. Also found: the quota check itself reads then resets the window non-atomically (`quota_service.py:311-320`). |
| R02-08 | Confirmed. The `test -f` backup check exists in two places: `check_remote_backups.sh` and `deploy/terraform/main.tf:12`. |
| R02-10 | **Extended.** The WebSocket also accepts API keys (`rudix_` prefix), so non-browser clients need a header path, not only tickets. |
| R02-12 | Confirmed. `_ws_rate_limit_chat` returns `True` on missing Redis and on any exception. |
| R02-13 | Confirmed. Seven 5-line stub files; the dead block is at `document_tasks.py:1690`; `RefreshTokenStore` has no callers. |
| New | R02-06 and R02-07 need Postgres to test, but the Postgres lane was scheduled for `0.3.0`. Added **R02-15**, a minimal Postgres job, to this version. |

## 3. Merge request sequence

One merge request per row, in this order. Rows in the same wave are independent.

| Wave | MR | Items | Size |
|---|---|---|---|
| 0 | Tag `v0.1.0` | R02-00 | S |
| 1 | Postgres test job | R02-15 | S |
| 1 | Task registration and routing | R02-04 | S |
| 1 | Beat service | R02-03 | S |
| 1 | Dead code and doc consistency | R02-13, R02-14 | S |
| 2 | Atomic quota | R02-07 | S |
| 2 | Retrieval sessions | R02-06 | S |
| 2 | Document claim and reaper | R02-02 | M |
| 2 | Index version isolation | R02-05 | M |
| 3 | Chat transport parity | R02-01 | L |
| 3 | WebSocket rate limiter mode | R02-12 | S |
| 3 | WebSocket ticket auth | R02-10 | M |
| 4 | Security headers | R02-09 | M |
| 4 | Build-time auth fallback check | R02-11 | S |
| 4 | Deployment fixes | R02-08 | M |

R02-02 depends on R02-03 (the reaper needs beat). R02-01 depends on R02-07. R02-10 should
merge after R02-01 and R02-12 because all three edit the same region of `chat.py`.

## 4. Steps per item

### R02-15 — Minimal Postgres test job

1. `backend/tests/conftest.py`: add a `pg_session` fixture.
   - Reads `TEST_DATABASE_URL`; `pytest.skip` when unset.
   - Session-scoped engine. Schema is created once by `alembic upgrade head`.
   - Per test: open a connection, begin a transaction, bind an `AsyncSession` with
     `join_transaction_mode="create_savepoint"`, roll back at teardown.
   - Add a second fixture `pg_session_factory` for tests that need several real connections
     (concurrency tests). These tests clean up their own rows by organisation ID.
2. `.github/workflows/ci.yml`: in the existing Alembic job (it already has Postgres and Redis
   services), add a step after the migration round trip:
   `.venv/bin/pytest -m "requires_postgres or requires_redis" -q` with `TEST_DATABASE_URL` set.
3. `backend/Makefile`: add `test-postgres`.
4. `backend/README.md`: document the marker and the variable.

Verify: the job passes with zero tests collected, then with the tests added by R02-06,
R02-07, and R02-02.

### R02-04 — Task registration and routing

1. `backend/app/workers/celery_app.py`:
   - Add `"app.workers.safety_eval_tasks"` to `include`.
   - Add `task_routes` entries: `safety_evals.run` to the evaluations queue,
     `documents.graph_reindex` and `documents.backfill` to the reindex queue,
     `agents.approvals.expire` to the default queue (explicit, not implicit).
2. New test `backend/tests/test_celery_task_registry.py`:
   - Import every `app/workers/*_tasks.py` module with `pkgutil`.
   - Assert each module is in `celery_app.conf.include`.
   - Assert every non-`celery.` task name in `celery_app.tasks` has a key in `task_routes`.
   - Assert every `beat_schedule` task name is registered.

### R02-03 — Beat service

1. `docker-compose.yml`, `deploy/compose/docker-compose.staging.yml`,
   `docker-compose.production.yml`, `docker-compose.integration.yml`: add a `beat` service that
   reuses the worker image and environment with
   `command: celery -A app.workers.celery_app:celery_app beat --loglevel=INFO
   --schedule /tmp/celerybeat-schedule`. No ports. `restart: unless-stopped`. Never scaled.
2. `backend/Makefile`: add `run-beat`. Root `Makefile`: no change (`make up` starts it).
3. `.github/workflows/release.yml`: next to "Verify worker is running" (line 317), add the
   same check for `beat`.
4. `deploy/terraform/main.tf`: no change; `up -d` starts every service in the file.
5. Docs: `backend/README.md` (process list), `docs/10_DEPLOYMENT_DOCKER.md`,
   `docs/17_CONNECTOR_OPERATIONS_RUNBOOK.md` (scheduled sync depends on beat).

Verify locally: `make up`, then `docker compose logs beat` shows
`Scheduler: Sending due task connector-sync-schedule-poll`.

### R02-13 and R02-14 — Dead code and doc consistency

1. Delete: `app/domains/admin/services/usage_service.py`,
   `app/domains/auth/services/auth_service.py`,
   `app/domains/chat/services/retrieval_service.py`,
   `app/domains/documents/services/document_service.py`,
   `app/domains/documents/services/extraction_service.py`,
   `app/domains/documents/services/storage_service.py`,
   `app/domains/evaluations/services/evaluation_service.py`,
   `app/auth/refresh_token_store.py`. Grep for imports first, including `__init__.py`
   re-exports and `tests/test_architecture_ddd.py`.
2. `document_tasks.py:1690`: remove the `if False and (...)` block and its body.
3. Add `deprecated=True` to the route decorators at `documents.py:727` and `chat.py:5390`.
   Regenerate `frontend/openapi.json` only if the committed file includes those paths.
4. Docs: align the status wording in `docs/25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md`
   (sections 4.4 and 4.5), `README.md:448`, `docs/README.md`, and `docs/CHANGELOG.md`.

### R02-07 — Atomic quota

1. `app/domains/quota/repositories/quota_repository.py`, `increment_usage`: replace the
   read-modify-write with an upsert that works on both dialects used in tests:

   ```python
   stmt = (
       insert(OrgQuotaUsage)  # dialect-specific insert chosen from session.bind.dialect.name
       .values(organization_id=organization_id, quota_type=quota_type,
               current_value=max(0, amount), next_reset_at=next_reset_at)
       .on_conflict_do_update(
           index_elements=["organization_id", "quota_type"],
           set_={"current_value": func.greatest(0, OrgQuotaUsage.current_value + amount)},
       )
       .returning(OrgQuotaUsage.current_value)
   )
   ```

   SQLite has no `greatest`; use `func.max` there. Keep the return type by re-reading the row
   after the statement.
2. `quota_service.py:316-320`, window reset: change `reset_usage` to a conditional update
   (`WHERE next_reset_at IS NULL OR next_reset_at <= :now`) so two requests cannot both reset.
3. Tests:
   - Existing quota tests pass unchanged on SQLite.
   - New `tests/test_quota_atomic_pg.py` (`requires_postgres`): 50 concurrent `increment_usage`
     calls on separate sessions from `pg_session_factory`; final value is 50.

Known limit, left for `0.5.0`: check and record are still separated by the pipeline, so a
burst can overshoot the limit by the number of in-flight requests. Document this in
`docs/07_API_DESIGN.md` next to the quota section.

### R02-06 — One session per concurrent keyword branch

1. `app/domains/chat/services/parallel_retrieval_optimizer.py`:
   - Add a constructor or call parameter `session_factory` defaulting to `SessionLocal`.
   - In the `keyword_search` branch factory, replace `session=session` with a helper:

     ```python
     async def _keyword(query: str) -> KeywordRetrievalResult:
         async with session_factory() as branch_session:
             return await keyword_retrieval_service.search_chunks(
                 session=branch_session, query=query, ...
             )
     ```

   - Leave graph expansion on the caller's session. It runs after the `gather`, so there is
     no concurrent use. Add a comment saying so.
   - In `_run_branch`, where `except Exception` sets `last_error_code`, also log at warning
     level with the branch name and increment
     `rudix_retrieval_branch_failures_total{branch,error}` in `app/core/metrics.py`.
2. Tests:
   - Unit: a fake `session_factory` records the sessions handed out; with three sub-queries
     assert three distinct sessions, none equal to the caller's.
   - `requires_postgres`: three sub-queries with keyword search on; all three
     `keyword_search` branch records have `succeeded=True`.

Note for `0.5.0`: making graph expansion truly parallel is a performance item, not a fix.

### R02-02 — Document claim and stale reaper

1. Migration `backend/alembic/versions/<date>_0001_document_processing_claim.py`, revises
   `20260715_0001`. Adds nullable `documents.processing_task_id` (`String(64)`) and
   `documents.processing_started_at` (timestamptz). Adds partial index
   `idx_documents_processing_started` on `(processing_started_at)` where
   `status = 'processing'`. Downgrade drops both.
2. `app/models/document.py`: add the two columns.
3. `app/core/config.py`: add `document_processing_stale_seconds` (default 3600, minimum 300)
   and `document_reaper_interval_seconds` (default 300). Add both to `.env.example`.
4. `app/domains/documents/repositories/documents.py`: add `claim_for_processing(session, *,
   document_id, task_id, stale_before, force) -> ClaimResult`. One `UPDATE ... RETURNING`:

   ```sql
   UPDATE documents
      SET status = 'processing', processing_task_id = :task_id,
          processing_started_at = now(), error_message = NULL
    WHERE id = :id
      AND ( :force
            OR status NOT IN ('processing', 'indexed', 'deleted')
            OR (status = 'processing'
                AND (processing_task_id = :task_id
                     OR processing_started_at IS NULL
                     OR processing_started_at < :stale_before)) )
   RETURNING id
   ```

   `ClaimResult` is `claimed`, `not_found`, or `held` (distinguish the last two with one
   follow-up read only when no row is returned). This keeps today's behaviour: `indexed` and
   `deleted` still skip unless `force`.
5. `app/workers/status_tracking.py`: add `claim_document_for_processing(...)` sync wrapper.
6. `app/workers/document_tasks.py`, `process_document` (line 3042 onward): replace the
   `get_document_status` / skip / `set_document_status` sequence (lines 3055-3081) with one
   call to the claim. Pass `self.request.root_id or self.request.id` as `task_id`, so a retry
   or redelivery of the same task matches. `held` returns `skipped`; `not_found` raises
   `PermanentTaskError`.
7. Clear the claim: in the success path that sets `indexed`, and in
   `DocumentTask.on_terminal_failure`, set both columns to `NULL`. Do it inside the existing
   status update so it is one statement.
8. Apply the same claim to `documents.reindex` (line 3263) if it uses the same skip pattern;
   read it before deciding.
9. Reaper: new task `documents.reap_stale` in a new file `app/workers/document_reaper_tasks.py`
   (do not add to the 3,468-line file).
   - Selects up to 100 documents with `status='processing'` and
     `processing_started_at < now() - stale` using `FOR UPDATE SKIP LOCKED`.
   - For each, sets `processing_started_at = NULL` and re-enqueues `documents.process` with the
     stored organisation and user IDs. A null start time makes the row claimable.
   - After `document_reaper_max_attempts` re-queues (new column not needed: count
     `FailedJob` rows or store a counter in `processing_metadata` if one exists; otherwise add
     `processing_attempts` integer to the same migration), mark the document `failed`.
   - Register in `include`, `task_routes`, and `beat_schedule`.
10. Tests in `tests/test_document_processing_claim.py`:
    - First claim succeeds; second claim with another task ID is `held`.
    - Claim with the same task ID succeeds again (retry and redelivery).
    - Stale claim can be taken over.
    - `indexed` skips; `force=True` claims.
    - Task-level: a first run raising `TransientTaskError` during embedding, then a second run
      with the same task ID, ends `indexed` with one set of chunks and vectors.
    - Reaper re-queues a stale document once and ignores a fresh one.
    - `requires_postgres`: two concurrent claims with different task IDs; exactly one wins.

Rollback: revert the code; the nullable columns are ignored by the previous version.

### R02-05 — Index version isolation

1. Staging check first (read-only): count Qdrant points and `document_chunks` rows whose
   `index_version` starts with `eval-`. Record the counts in the merge request.
2. Production retrieval passes the active version:
   - `chat.py`: every call into `query_retrieval_service` and the parallel optimizer passes
     `index_version=settings.document_index_version`. Add the parameter to
     `ParallelRetrievalOptimizer.retrieve` and forward it to `retrieve_candidates`
     (`parallel_retrieval_optimizer.py:225`).
   - `keyword_retrieval_service.search_chunks`: add `index_version: str | None` and
     `.where(DocumentChunk.index_version == index_version)` when set.
   - Agent tool path `document_intelligence_tools.py:643` and the MCP retrieval path: same.
   - Evaluation runs keep passing their own target version (they already do, lines 1344-1458).
3. Evaluation cleanup in `app/workers/evaluation_tasks.py`: wrap the per-target block
   (from line 1319) in `try/finally`. In `finally`, when `target_index_version` starts with
   `eval-`, call `_qdrant_service.delete_document_points(document_id, index_version=...)` and
   `_document_repository.delete_document_chunks(..., index_version=...)` for each document.
   Cleanup failure is logged and recorded in the run summary; it does not fail the run.
4. Separate collection for evaluation vectors is **moved to R06-12**. With the filter and the
   cleanup in place it is no longer needed for correctness, and it needs a collection-name
   parameter threaded through the ingestion coroutine that `0.6.0` rewrites.
5. Script `backend/scripts/purge_eval_index_versions.py`: `--dry-run` (default) lists counts
   per organisation; `--apply` deletes Qdrant points by filter
   `index_version` prefix match (scroll and delete by ID, since payload match is exact) and
   chunk rows `WHERE index_version LIKE 'eval-%'`, skipping runs whose status is `running`.
6. Tests:
   - `tests/test_rag_isolation.py` (marker `isolation`): same document under `v1` and
     `eval-abc-1`; vector and keyword retrieval through the chat path return only `v1`.
   - Evaluation task test: after a chunking-comparison run, no `eval-` chunks remain; also
     when a question raises midway.
7. Docs: `docs/03_RAG_WORKFLOW.md` (index version is a mandatory retrieval filter),
   `docs/12_EVALUATION_AND_MONITORING.md` (cleanup and purge script).

Risk: an organisation whose chunks were indexed under an older `DOCUMENT_INDEX_VERSION` would
return nothing after the filter is added. Before merging, run
`SELECT index_version, count(*) FROM document_chunks GROUP BY 1` on staging and production.
If more than one non-eval version exists, reindex first or make the filter a list setting
`DOCUMENT_ACTIVE_INDEX_VERSIONS`.

### R02-01 — Chat transport parity

New package `backend/app/application/chat/` with three small modules. `chat.py` only loses
lines in this merge request.

1. `application/chat/quota.py`:
   - `async def ensure_chat_quota(db_session, *, organization_id) -> None` wrapping the call
     at `chat.py:2980-2987`.
   - `async def record_chat_usage(db_session, *, organization_id) -> None` wrapping
     `chat.py:4897-4902`.
2. `application/chat/citation_access.py`:
   - `async def filter_chunks_by_cite_access(db_session, *, principal, organization_id,
     user_id, user_roles, chunks) -> list[Chunk]`. Move `chat.py:3577-3619` here unchanged in
     behaviour, with one improvement: fetch the documents with a single
     `DocumentRepository.get_documents_by_ids` call (add it if missing) instead of one query
     per document. Owner and admin short-circuit stays.
3. HTTP path: replace the three inline blocks with calls to the new functions. No behaviour
   change; existing tests must pass untouched.
4. WebSocket path, `_run_ws_chat_pipeline`:
   - After `async with SessionLocal() as db_session:` (line 6201) and before scope validation,
     call `ensure_chat_quota`. Catch the plan-limit exception and
     `await send("chat.error", safe_error_code="quota_exceeded")`, then return. Add
     `quota_exceeded` to the outbound error-code enum in the WS schema and to the frontend
     error map (`frontend/src/lib/chat-websocket.ts` types and the chat error messages in all
     six locale files).
   - After retrieval and before reranking, at the point that mirrors `chat.py:3577`, call
     `filter_chunks_by_cite_access`.
   - Next to the WS usage event (`chat.py:7158`), before the commit at 7297, call
     `record_chat_usage`.
5. Tests, new `tests/test_chat_transport_parity.py`:
   - Parametrised over transport (`http`, `ws`), with a stubbed provider and retrieval:
     over-quota organisation is refused and no assistant message is persisted; successful
     question increments `questions` usage by exactly 1; a `member` who cannot cite document B
     gets citations only from document A; an `admin` gets both.
   - Mark with `isolation`.
6. Docs: `docs/07_API_DESIGN.md` (WS error code), `docs/22_AUTHORIZATION_SYSTEM.md`
   (cite check applies to both transports), security checklist.

Rollout: no flag. This closes a gap; a flag would keep the gap available.

### R02-12 — WebSocket rate limiter failure mode

1. `chat.py`, `_ws_rate_limit_chat` (line 6034): in both the `redis is None` branch and the
   `except` branch, return `False` when
   `settings.rate_limit_redis_failure_mode == RateLimitRedisFailureMode.closed`, and log
   `rate_limit.redis_unavailable` as the HTTP dependency does. Better: move the function into
   `app/rate_limit/` beside `enforce_rate_limit` and share `_build_key` and the failure
   handling.
2. Tests: Redis `None` and Redis raising, each under `open` and `closed`.

### R02-10 — WebSocket ticket authentication

1. `app/core/config.py`: `chat_ws_ticket_ttl_seconds` (default 30),
   `chat_ws_allow_query_token` (default `True` in this version). `.env.example` too.
2. New `app/domains/chat/services/ws_ticket_service.py`:
   - `issue(principal, session_id) -> str`: 32 random bytes, URL-safe. Store
     `rudix:ws_ticket:{sha256(ticket)}` in Redis with the TTL. Value: user ID, organisation
     ID, roles, auth session ID, issued-at.
   - `redeem(ticket) -> TicketClaims | None`: `GETDEL`, so a ticket works once.
   - Redis unavailable: issue returns 503; redeem returns `None`.
3. `chat.py` (or a new `interfaces/http/chat_ws_ticket.py` to avoid growing `chat.py`):
   `POST /api/v1/chat/ws-ticket`, authenticated, rate-limited with the chat scope, returns
   `{"ticket": "...", "expires_in": 30}`.
4. `chat_websocket` (line 7534): accept, in order:
   1. `?ticket=`: redeem, then rebuild the principal by loading the user's current
      membership and session, so a revoked session cannot use a ticket.
   2. `Authorization: Bearer` header on the handshake, for API keys and service accounts
      (non-browser clients can set headers).
   3. `?token=`, only when `chat_ws_allow_query_token` is true. Log
      `chat.ws.query_token_used` with the user ID so remaining callers can be found.
5. Frontend:
   - `src/lib/api/chat.ts`: `createChatWsTicket()`.
   - `src/lib/chat-websocket.ts:112`: `ChatWSClientOptions` takes
     `getTicket: () => Promise<string>` instead of `token`; `connect()` becomes async and sets
     `ticket`. `src/lib/use-chat-websocket.ts` passes the function.
   - Update the WS client tests and MSW handlers.
6. Tests: single use (second redeem fails), expiry, ticket for organisation A cannot open a
   socket as organisation B, revoked session rejected, header auth with an API key,
   `?token=` rejected when the flag is false.
7. Docs: `docs/07_API_DESIGN.md` (handshake options, deprecation of `?token=`),
   `frontend/README.md`, security checklist.

### R02-09 — Security headers

1. `frontend/src/lib/security-headers.ts` (new, unit-testable): builds the header list from
   `NEXT_PUBLIC_API_URL`, the WebSocket origin, and the analytics hosts used by
   `ConsentProvider.tsx`.
2. `frontend/next.config.ts`: add `async headers()` returning, for `/:path*`:
   `Strict-Transport-Security` (production-like only), `X-Content-Type-Options: nosniff`,
   `Referrer-Policy: strict-origin-when-cross-origin`,
   `Permissions-Policy` (camera, microphone, geolocation off),
   and `Content-Security-Policy-Report-Only` with `frame-ancestors 'none'`.
   - `script-src`: `'self'` plus the consent-gated analytics hosts. The inline JSON-LD and
     analytics snippets need a nonce or hashes. Read the CSP guide in
     `frontend/node_modules/next/dist/docs` for how this Next.js version supplies nonces
     before choosing; hashes work with static generation and nonces do not.
   - `style-src`: `'self' 'unsafe-inline' https://fonts.googleapis.com`;
     `font-src`: `'self' https://fonts.gstatic.com` (until `R07-04`).
   - `connect-src`: `'self'`, API origin, WebSocket origin, Sentry and analytics hosts.
   - `img-src`: `'self' data: blob:` plus the avatar origin.
3. Backend: new `app/core/security_headers.py` middleware adding `nosniff`, `Referrer-Policy`,
   `X-Frame-Options: DENY`, and HSTS when `environment` is production-like. Register in
   `main.py` after the request-ID middleware. Skip `/docs` assets if they break.
4. Tests: unit test for the header builder; backend middleware test; Playwright assertions in
   `frontend/e2e` on `/` and `/login` for header presence.
5. Enforcement (switch from report-only) is `R03-08`, after a week of clean reports.

### R02-11 — Reject dev auth fallback in production-like builds

1. `frontend/next.config.ts`, inside the existing `phase-production-build` block after the
   URL loop: when `isProductionLike`, push an error for each of
   `NEXT_PUBLIC_AUTH_LOCAL_FALLBACK === "true"`, a non-empty
   `NEXT_PUBLIC_AUTH_LOCAL_PASSWORD`, and a non-empty
   `NEXT_PUBLIC_AUTH_DEFAULT_ACCESS_TOKEN`.
2. Extract the validation into a pure function in a `.mjs` or inline helper that the config
   can import at server start (the existing comment at the top of the block explains why
   `.ts` imports from `src/` crash there). Unit-test the function.
3. `frontend/README.md`: note the three variables are development-only.

### R02-08 — Deployment fixes

1. `deploy/terraform/variables.tf`: add `infra_services` (string, default
   `"postgres rabbitmq redis minio qdrant"`). `main.tf:11`: use it.
   `.github/workflows/release.yml`: set `TF_VAR_infra_services` with `neo4j` appended for
   staging only.
2. Backup gate:
   - `deploy/scripts/check_remote_backups.sh`: for each path, accept a file or a directory,
     and require a file modified within `DEPLOY_BACKUP_MAX_AGE_HOURS` (default 26):
     `find "$p" -type f -mmin -$((H*60)) | head -1 | grep -q .`.
   - `main.tf:12`: remove the inline `test -f` and rely on the script, which already runs in
     the production job at `release.yml:539`.
   - `DEPLOYMENT.md:186-188`: state the expected layout.
3. `docker-compose.production.yml` and `docker-compose.staging.yml`:
   - Volumes for `rabbitmq` (`/var/lib/rabbitmq`) and `redis` (`/data`, with
     `--appendonly yes`), and `--requirepass ${REDIS_PASSWORD}`; update `REDIS_URL` and the
     healthcheck.
   - Pin `qdrant/qdrant`, the MinIO image, and `rabbitmq` to the versions currently running
     (read them from the staging host; do not guess).
   - ClamAV: add the `clamav` service from `docker-compose.yml` and set
     `MALWARE_SCAN_CLAMAV_HOST: clamav` on `api` and `worker`.
4. `app/core/config.py`, in the production validator near line 1236: fail when
   `malware_scan_enabled` is true, the environment is production-like, and
   `malware_scan_clamav_host` is `localhost`.
5. Verify: `terraform fmt -check`, `terraform validate`,
   `docker compose -f deploy/compose/docker-compose.production.yml config` with a sample env
   file, and the integration smoke in `release.yml`.

Data safety: adding a Redis password and volumes recreates those containers. Deploy in a
maintenance window; in-flight Celery results and rate-limit counters are lost, queued
RabbitMQ messages are lost once (they are already lost on every recreate today).

## 5. Verification for the release

Run from the repository root before tagging `v0.2.0`:

```bash
make check-all
cd backend && make test-postgres
cd frontend && npm run test:e2e && npm run build
```

Then on staging:

1. Beat log shows the connector poll and the reaper firing.
2. Upload a document, `docker kill` the worker mid-processing, restart it; the document
   reaches `indexed` with one set of chunks.
3. Ask one question over WebSocket as a member without access to a cited document; the
   citation is absent.
4. Set the organisation's question quota to its current usage; the next WebSocket question
   returns `quota_exceeded`.
5. `curl -I` on the app and API shows the security headers.

## 6. Change Notes

- 2026-11-26: Initial version, written after checking the `0.2.0` spec against the code.
