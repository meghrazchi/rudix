# v0.4.0 — Detailed Implementation Plan

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-27
- `Related Docs`: [V0_4_0_DATA_LAYER_PERFORMANCE.md](./V0_4_0_DATA_LAYER_PERFORMANCE.md),
  [V0_3_0_IMPLEMENTATION_PLAN.md](./V0_3_0_IMPLEMENTATION_PLAN.md),
  [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../06_DATABASE_SCHEMA.md](../06_DATABASE_SCHEMA.md),
  [../22_AUTHORIZATION_SYSTEM.md](../22_AUTHORIZATION_SYSTEM.md)

## 1. Purpose

Turn the `0.4.0` spec into eight work packages with exact files, symbols, tests, and owners of
shared files. Every reference was read on `feat/v0.4.0-data-layer-performance` at `f9d432b`
(`0.2.0` and `0.3.0` implemented, not tagged). Line numbers drift; search for the quoted symbol.

Prerequisite (separate step, not part of this plan): the 42 failing Playwright tests are fixed
first. The `cryptography` pin and the push of `develop` stay as they are.

Evidence rule: no load test can run before staging. Performance claims in this version rest on
statement-count assertions and `EXPLAIN` on the test database. No latency figure is recorded.

## 2. Plan check: what the code confirmed or changed

| Item | Result |
|---|---|
| R04-01 | Confirmed: `app/db/session.py` sets only `pool_pre_ping` and `pool_recycle`; no `engine.dispose()` in `app/core/lifespan.py`. **Changed:** pool gauges `rudix_db_pool_checked_out`/`_size`/`_overflow` already exist (R03-09, `app/core/db_metrics.py`); only a wait histogram and a timeout counter are missing. Timeouts default to off (current behaviour); recommended values go in staging/production env. In PgBouncer transaction mode startup parameters are ignored, so timeouts are also set per transaction. Request-path network calls inside a session outside chat: `model_provider_diagnostics.py` (`provider.complete`/`embed` probe), `admin_webhooks.py` (test delivery, `httpx`), `admin_sso.py` (`test_connection`). `agent_runs.py` runs agents in the request; that moves to workers in `R06-13`. |
| R04-02 | **Changed.** Already present: `citations(chat_message_id)` (`idx_citations_message`), `connector_sync_runs(connection_id, status)`, `organization_members(organization_id, user_id)`. Missing and added: `documents(organization_id, created_at DESC, id DESC)` (default document list sort, no index today), `chat_sessions(organization_id, user_id, updated_at DESC, id DESC)` (the session list sorts by `updated_at`, not `created_at`), `webhook_deliveries(webhook_id, created_at DESC)` and `(organization_id, created_at)`. The test database has 154 single-column foreign keys without a leading index and no `pg_stat_statements`; the guard test uses an exemption file for the existing ones. Indexes on an empty test database are proven usable with `enable_seqscan = off`, not chosen by cost. |
| R04-03 | Confirmed: per-message citation queries in `list_chat_session_messages` and `get_shared_session` (`chat.py`), per-row counts in `collections.py` (three list sites), `documents.py` `list_documents` (`count_document_chunks`), `connectors.py` (`_connection_indexed_document_count`), `evaluation_sets.py` (`count_evaluation_questions`), per-ID loop in `ensure_document_ids_access` (`app/auth/dependencies.py`). `create_citation` does `flush` + `refresh` per citation (two statements each) at two chat sites. A per-request counter exists (`rudix_db_queries_per_request`); the spec's `rudix_db_statements_per_request` is that metric and keeps its name. |
| R04-04 | **Changed.** Sort keys differ per endpoint: sessions `(updated_at DESC, id DESC)`, messages `(created_at, role rank, id)` ascending, documents only when `sort_by=created_at`. Cursors encode the endpoint's own sort tuple, not always `(created_at, id)`. There is no list endpoint for usage events or activity timeline events; they get nothing. Webhook deliveries return a fixed page with no parameters. `total` stays the default when no cursor is sent (backward compatible). The usage export loads every matching row and slices `events[:limit]` in Python (limit not in SQL); the audit export is capped at 10,000, not 50,000. Both exports use `json.dumps(sort_keys=True)`, so `items` precedes `returned` and can be streamed byte-compatibly. |
| R04-05 | Confirmed: `AppAuthProvider.authenticate` reads the session (one or two queries) and the user with memberships; `require_permission` reads the membership and the custom-role permissions; `require_feature` reads the override. **Changed scope:** this version caches the auth principal snapshot, permission sets, and feature-flag overrides; AI policy, RAG profile, model profile, tool policy, and quota policy namespaces are added by `0.5.0` when the chat pipeline is rebuilt on the cache. No Redis is available here and `fakeredis` is not installed; tests use a shared in-repo fake. |
| R04-06 | **Changed.** There is no usage *row* per API-key request, only `UPDATE ... last_used_at/last_used_ip` on `api_keys`, `service_account_tokens`, and `service_accounts`. Those updates are never committed on read-only requests (rolled back at session close) and hold a row lock for the whole request. Batching fixes both. |
| R04-07 | Confirmed: `app/rate_limit/counter.py` does `INCR` + `EXPIRE` + `TTL` (up to four round trips). The same pattern is copied in `interfaces/http/auth.py`, `public_contact.py`, `app/mcp/rate_limit.py`, and `domains/bots/services/rate_limit.py`; all move to the shared primitive. The Lua script cannot be executed here (no Redis, no `lupa`); the fake runs a Python reference of the same algorithm, and a `requires_redis` test runs the real script in CI. |
| R04-08 | Confirmed: `set_postgres_tenant_context` has no caller; `bind_session_tenant` is called once (`get_current_principal`) without `enforce_guard`; the policy passes when the setting is NULL. **Changed:** (1) the 2026-07-15 migration imports `TENANT_RLS_TABLES` and `build_enable_rls_sql` at run time, so both stay frozen and new names are added; (2) pre-auth lookups (API-key and service-account hash lookup, share tokens, invitations, SSO discovery, SCIM, OAuth state, bot inbound, public status) read org-scoped tables before a tenant is known, so those tables get a "lookup" policy that never denies on NULL; (3) the test role `rudix` is superuser and `BYPASSRLS`, so isolation is proven by `SET LOCAL ROLE` to a probe role created in the test transaction; (4) `chat_messages`, `citations`, `document_chunks`, and `document_pages` have no `organization_id` and stay outside RLS; (5) the WebSocket path (`SessionLocal()` in `chat.py`) and Celery tasks do not bind a tenant, so `strict` stays non-default (rollout unchanged: `soft` now, `strict` default in `0.5.0`). `FORCE ROW LEVEL SECURITY` is not applied by the migration: strict relies on the app connecting as a non-owner role; FORCE moves to `0.5.0` with the role split. |
| R04-09 | **Changed.** None of the five tables is new, all hold production data, and none is referenced by a foreign key. Converting them needs a rehearsal on staging volume and a maintenance window, so the conversion is deferred. This version ships per-table retention by batched delete (using the `(organization_id, created_at)` indexes), organisation-configurable audit retention, a partition helper and maintenance task that act only on tables that are already partitioned, and a tested, not auto-applied migration procedure. Usage events feed quotas and invoices, so every retention default is "keep". |
| R04-10 | **Changed.** No global handlers exist; 647 string `detail=` call sites. `docs/07` already documents `{"error": {...}}` with upper-snake codes, so the doc is aspirational today. Call sites in the hot routers are edited by other packages, so this version derives codes centrally (a registry of the most frequent detail strings plus a status fallback) and migrates no call site; per-router migration starts in `0.5.0`. The frontend parser reads `error` only as a string today. |
| R04-11 | Confirmed: sync boto3 in `documents.py` (download), `profile.py` (avatar), `application/documents/workflows.py` (upload); nine `.delay()` call sites on request paths; `QueryRetrievalService.retrieve_candidates` is sync and called from `embed_and_retrieve`. **Changed:** retrieval moves to `asyncio.to_thread` now; `AsyncQdrantClient` lands with `R06-07`. The outbox table is deferred to `R06-01`. Starlette 1.10 GZip already skips `text/event-stream`. |
| R04-12 | Confirmed: `run_graph_migrations()` in lifespan; `config.py` is 1,733 lines with one 250-line validator. **Changed:** `init_redis`, `init_rabbitmq`, and `init_qdrant` re-raise and abort boot; Neo4j is already non-fatal. "Nested settings modules" becomes per-area mixins composed into one flat `Settings`, because about 120 modules read `settings.<field>` and nested models would change environment names. |
| R04-13 | **Changed.** `evaluations.py` already has no `select(` and no `.commit(`. `documents.py` has 5 selects and 1 commit, `admin.py` 3 selects. `auth.py` (18 commits) is also edited by D1 and is auth-critical; `agent_runs.py` (7 commits) is rewritten by `R06-13`. Both are deferred. |
| Other | The usage dashboard loads every event of the range into Python (`list_usage_events_filtered` has no limit); recorded as a follow-up, not fixed here. Citation order within one answer relies on `created_at`, which is the transaction time for all rows; a `position` column is a follow-up. |

## 3. Sequence

| Chain | Order | Task | Items | Model | Review |
|---|---|---|---|---|---|
| A | 1 | A1 | R04-02 index migrations and foreign-key guard | opus | data |
| A | 2 | A2 | R04-01 engine and pool, R04-08 tenant RLS | opus | data |
| A | 3 | A3 | R04-09 retention and partition tooling | opus | data |
| B | 1 | B1 | R04-03 N+1, R04-04 keyset pagination and export streaming | opus | data |
| B | 2 | B2 | R04-13 handler refactor, R04-11 event loop | sonnet | api |
| C | 1 | C1 | R04-10 error envelope, R04-12 startup and config split | sonnet | api |
| D | 1 | D1 | R04-07 atomic rate limiting, R04-06 batched usage writes | opus | data |
| D | 2 | D2 | R04-05 application cache | opus | data |

All migrations live in chain A, so there is one linear history:

| Revision | down_revision | Task | Content |
|---|---|---|---|
| `20261127_0001` | `20261126_0001` | A1 | chat, activity, share, notification, citation indexes |
| `20261127_0002` | `20261127_0001` | A1 | document, connector, source, evaluation, webhook indexes |
| `20261127_0003` | `20261127_0002` | A1 | membership, usage, audit indexes |
| `20261127_0004` | `20261127_0003` | A2 | mode-aware tenant policies on every `organization_id` table |
| `20261127_0005` | `20261127_0004` | A3 | `organization_governance_policies.audit_log_retention_days` |

No other task adds a migration. `make check-revisions` must report one head after each.

## 4. Shared files and contracts

### 4.1 Owners and anchors

Every task re-reads a shared file immediately before editing it, edits only its anchor with
`Edit` (never a whole-file `Write` of a shared file), and re-reads after a failed `Edit`.

| File | Task: anchor |
|---|---|
| `backend/app/core/config.py` | New fields are inserted directly after an existing field: A2 after `database_echo`; A3 after `document_reaper_batch_size`; D1 after `rate_limit_auth_password_requests`; D2 after `redis_socket_timeout_seconds`; B2 after `metrics_db_query_counting_enabled`; C1 after `neo4j_uri`. C1 then splits the file (4.2 item 5). If the anchor field has moved into `app/core/settings/*.py`, insert after it there. |
| `.env.example` | A2 after `DATABASE_ECHO=`; A3 after `DOCUMENT_REAPER_BATCH_SIZE=`; D1 after `RATE_LIMIT_CONTACT_REQUESTS=`; D2 after `REDIS_SOCKET_TIMEOUT_SECONDS=`; B2 after `METRICS_DB_QUERY_COUNTING_ENABLED=`; C1 after `ENTERPRISE_GRAPH_ENABLED=`. |
| `backend/app/db/session.py` | A2 owns the file. D2 adds one line, `install_cache_invalidation_listeners()`, directly after `install_sqlalchemy_tenant_guard()`. |
| `backend/app/auth/dependencies.py` | A2: `get_current_principal`. B1: `ensure_document_ids_access`. D1: `_authenticate_api_key`, `_authenticate_service_account_token`. D2: `require_permission`, `require_feature`. |
| `backend/app/core/lifespan.py` | C1 owns the body. A2 adds `await dispose_engine()` in `finally` after `await close_neo4j()`. B2 adds the loop-lag monitor start after `await probe_local_providers()` and stop before `shutdown_langfuse()`. C1 keeps both. |
| `backend/app/main.py` | C1: `register_exception_handlers(app)` directly after the `app = FastAPI(...)` call. B2: `GZipMiddleware` directly after `attach_metrics_middleware(app)`. |
| `backend/app/workers/celery_app.py` | `include`: D1 after `"app.workers.agent_tasks",`, A3 after `"app.workers.safety_eval_tasks",`. `beat_schedule`: D1 after the `"agent-approvals-expire"` entry, A3 after the `"documents-reap-stale"` entry. `task_routes`: D1 after `"agents.approvals.expire"`, A3 after `"documents.reap_stale"`. |
| `backend/app/interfaces/http/chat.py` | B1 only: `list_chat_sessions` handler, `list_chat_session_messages`, `get_shared_session`, and the two `create_citation` loops. |
| `documents.py`, `admin.py` (HTTP) | B1 (`list_documents`, `export_admin_usage`, `list_admin_audit_logs`, `export_admin_audit_logs`), then B2 (everything else). |
| `profile.py` | B2: avatar functions (`_avatar_presigned_url`, upload, delete). No other task. |
| `admin_webhooks.py` | A2: the test-delivery handler. B1: `list_webhook_deliveries`. |
| `backend/tests/conftest.py` | A2 only (probe-role fixture). |
| `infra/observability/prometheus/alerts.yml` | A2 then A3: new groups appended at the end. |
| `frontend/openapi.json`, `frontend/src/lib/api/generated/*` | Regenerated with `npm run api:update-schema` by B1 and A3 after their API changes; the release step re-runs the check. |
| `frontend/src/lib/api/errors.ts` (+ test) | C1 only. |
| `docs/07_API_DESIGN.md` | B1: new `## Pagination` before `## Quotas and plan limits`. C1: body of `## Error format`. |
| `docs/06_DATABASE_SCHEMA.md` | A1: `## Recommended indexes`. A2, A3: new sections before `## Qdrant payload schema`. |
| `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` | A2: `## Authorization`, `### Database`. A3: `## Audit logs`. D1: `## Rate limiting`. D2: new `## Caching of security-sensitive data` before `## Logging safety`. C1: first bullet of `### API`. B2: last bullet of `### API`. |
| `docs/12_EVALUATION_AND_MONITORING.md` | A2, A3, B2, D1, D2: one `###` subsection each, inserted before `## Continuous evaluation`. |
| `backend/README.md` | A2, C1: text before `## Authentication quick check`. A3, D1: rows before `## Prometheus & Grafana Observability`. D2: `## Application cache` before `## Useful task commands`. |
| `docs/CHANGELOG.md` | One line per task under `[Unreleased]` `### Added`, directly after the line starting "- `docs/roadmap/V0_4_0_IMPLEMENTATION_PLAN.md`". |

### 4.2 Contracts between chains

1. **Postgres databases per chain.** Never downgrade or share `rudix_test`. Each chain creates
   its own database on the same server (`rudix_test_a` … `rudix_test_d`) and points
   `TEST_DATABASE_URL` at it; A uses `rudix_test_migrations` for downgrade round trips:

   ```bash
   cd backend && .venv/bin/python -c "
   import asyncio, asyncpg
   async def main(name):
       c = await asyncpg.connect('postgresql://rudix:rudix@127.0.0.1:55432/postgres')
       if not await c.fetchval('select 1 from pg_database where datname=\$1', name):
           await c.execute(f'CREATE DATABASE {name}')
       await c.close()
   asyncio.run(main('rudix_test_b'))"
   ```

   Chain A writes each migration file in one `Write` and immediately runs it against
   `rudix_test_migrations`, because every chain's `pg_migrated_url` applies the current head.
2. **Session-context marker (A2 defines).** The per-transaction `set_config` statement starts
   with the SQL comment `/* rudix:session-context */`. Every statement-count helper (B1's
   `tests/query_count.py`, D2's inline counter) ignores statements containing that marker.
3. **Redis fake (D1 defines, D2 extends).** `backend/tests/redis_fakes.py`: `FakeRedis`
   (`get`, `set(ex=, nx=)`, `incr`, `delete`, `expire`, `ttl`, `hset`, `hgetall`, `sadd`,
   `spop`, `register_script`) and `BrokenRedis`. `register_script(source)` returns a callable
   that dispatches on a registered Python reference implementation keyed by the script's
   SHA1. Existing per-file fakes move to it.
4. **Maintenance sessions (A2 defines).** `app.db.session.maintenance_session()` (async context
   manager, sets `session.info["rls_maintenance"] = True`, binds to `DATABASE_MAINTENANCE_URL`
   when set). Cross-tenant beat tasks use it, including A3's retention task and D1's flush
   task; D1 falls back to `SessionLocal()` if A2 has not landed and leaves a `TODO(R04-08)`.
5. **Settings split (C1).** Before splitting, C1 writes `tests/fixtures/settings_fields.txt`
   (one `field|env-name` line per field). The test checks the live field set is a superset of
   that file, so fields added by other chains while the split is in progress are not lost. The
   split moves blocks with `Edit`; on a failed `Edit` C1 re-reads and keeps the new lines.
6. **Error codes (C1).** Upper snake case (`DOCUMENT_NOT_FOUND`), as `docs/07` documents.
   Other tasks raise `HTTPException` as today; new 400s for cursors use detail strings
   `Invalid pagination cursor` and `Cursor pagination requires sort_by=created_at`, which C1
   maps to `INVALID_CURSOR` and `CURSOR_SORT_UNSUPPORTED`.

## 5. Steps per item

### R04-02 — Indexes (A1)

1. Three migrations (section 3). Each: on PostgreSQL, inside
   `op.get_context().autocommit_block()`, `SET statement_timeout = 0`, drop the index only if
   `pg_index.indisvalid` is false, then `op.create_index(..., postgresql_concurrently=True,
   if_not_exists=True)`; downgrade drops concurrently. On SQLite, plain `create_index`.
2. Indexes: `chat_sessions(organization_id, created_at DESC)` and
   `(organization_id, user_id, updated_at DESC, id DESC)`; `activity_timeline_events`,
   `chat_shares`, `notifications` `(organization_id, created_at DESC)`; `citations(document_id)`,
   `citations(chunk_id)`; `documents(organization_id, created_at DESC, id DESC)`;
   `external_items(connection_id)`; `source_documents(document_id)`;
   `evaluation_results(evaluation_question_id)`; `webhook_deliveries(webhook_id, created_at DESC)`
   and `(organization_id, created_at)`; `organization_members(user_id)`;
   `usage_events(user_id, created_at)`; `audit_logs(user_id, created_at)`. Matching `Index`
   entries in the models' `__table_args__`.
3. `tests/test_fk_index_guard.py`: every single-column foreign key in `Base.metadata` is the
   leading column of an index or unique constraint, or listed in
   `tests/fixtures/fk_index_exemptions.txt`; a Postgres twin reads `pg_constraint`/`pg_index`.
4. `tests/test_query_plans_pg.py`: ten hot queries (document list, session list, message list,
   citations by message IDs, notification list, audit list, usage range, membership by user,
   API key by hash, auth session by ID) under `SET LOCAL enable_seqscan = off` show no
   `Seq Scan` on the target table.

### R04-01 and R04-08 — Engine, pool, and tenant RLS (A2)

1. Settings: `DB_POOL_SIZE` (5), `DB_MAX_OVERFLOW` (10), `DB_POOL_TIMEOUT` (30 s),
   `DB_STATEMENT_TIMEOUT_MS` (0 = off), `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` (0),
   `DB_PGBOUNCER_MODE` (false), `DATABASE_MIGRATION_URL`, `DATABASE_MAINTENANCE_URL`,
   `RLS_ENFORCEMENT` (`off|soft|strict`; unset means `soft` in staging/production, `off`
   elsewhere).
2. `session.py`: timeouts through `connect_args={"server_settings": ...}`; PgBouncer mode sets
   `statement_cache_size=0`, `prepared_statement_cache_size=0`, unique prepared statement names,
   and moves timeouts into the per-transaction statement; `dispose_engine()`; a timed pool
   subclass feeding `rudix_db_pool_wait_seconds` and `rudix_db_pool_timeouts_total`.
3. `alembic/env.py` uses `DATABASE_MIGRATION_URL` when set.
4. Tenant context: `after_begin` listener runs `/* rudix:session-context */ SELECT set_config(...)`
   for org, `app.rls_mode`, and (PgBouncer) timeouts; `apply_tenant_context(session)` runs it
   for the open transaction after `get_current_principal` binds the tenant
   (`enforce_guard=True` only in `strict`). Soft mode logs and counts
   `rudix_rls_soft_denials_total{table}` for ORM statements and flushes on RLS tables with no
   bound tenant (throttled logs, maintenance sessions excluded).
5. Migration `20261127_0004`: literal table lists. Strict-capable policy denies NULL only when
   `app.rls_mode = 'strict'`; lookup policy keeps today's NULL-permissive condition.
   `SET lock_timeout = '5s'`. Downgrade restores the 12-table legacy state.
6. `deploy/sql/provision_roles.sql`: `rudix_app` (no superuser, no `BYPASSRLS`, not owner, DML
   grants, default privileges) and `rudix_maintenance` (`BYPASSRLS`). Not auto-applied.
7. Release the connection before network calls in the three handlers (2 above).
8. Tests: probe-role isolation on Postgres (strict hides other orgs with no app filter, denies
   NULL, `WITH CHECK` rejects cross-org insert; soft and off unchanged); coverage test that
   every `organization_id` table is in a list; soft-mode logging on SQLite; F144 suite with the
   ORM guard on; pool timeout counter; `in_transaction()` is false during the fake network call.

### R04-09 — Retention and partition tooling (A3)

Settings `RETENTION_<TABLE>_DAYS` for the five tables (unset = keep, minimum 7, audit minimum
30), `RETENTION_DELETE_BATCH_SIZE`, `RETENTION_MAX_BATCHES_PER_RUN`. Migration
`20261127_0005` adds the nullable audit override (check `>= 30`), exposed through
`GovernancePolicyUpdateRequest`. Task `maintenance.retention.purge` (daily) deletes per
organisation in batches with an injected `now`; `maintenance.partitions.ensure` (daily) acts only
on tables in `pg_partitioned_table`, creates next month's partition, drops expired ones, and sets
`rudix_partition_missing{table}`. `scripts/partition_table.py` (`plan`, `create-shadow`,
`backfill --batch-size`, `swap`, `verify`) is tested against a scratch table on Postgres,
including a resumed backfill and pruning visible in `EXPLAIN`.

### R04-03 and R04-04 — N+1 and keyset pagination (B1)

Batched repository methods for citations, chunk counts, collection counts, connection counts,
question counts, and `ensure_document_ids_access`; `create_citations_bulk` (client-side IDs, one
flush, no refresh). `app/shared/pagination/cursor.py` with opaque versioned cursors and row-value
comparisons. `cursor`, `include_total`, `next_cursor` on sessions, messages, documents,
notifications, audit logs, and webhook deliveries. Both exports stream from a dedicated tenant-bound
session with `stream_results`, with the limit in SQL. Tests: equal statement counts at 2 and 12
rows, cursor walk equals offset walk (both dialects), tampered cursor gives 400, cross-org
cursor returns nothing, streamed export equals the old bytes.

### R04-13 and R04-11 — Handlers and event loop (B2)

`documents.py` and `admin.py` lose every `select(` and `.commit(` to repositories and
`app/application/*` workflows with no behaviour change. `app/clients/object_storage.py`
(`asyncio.to_thread` wrappers, chunked body reads), `app/workers/dispatch.py` `enqueue()` for the
nine `.delay()` sites, `to_thread` retrieval in `embed_and_retrieve`, `GZipMiddleware`
(`HTTP_GZIP_MINIMUM_BYTES` 1024), and `app/core/loop_lag.py` (`rudix_event_loop_lag_seconds`).
Tests: lag probe under 100 ms with a 300 ms blocking fake during upload, download, and
retrieval, and a control test that the probe detects an unwrapped call.

### R04-10 and R04-12 — Errors, startup, configuration (C1)

`app/core/errors.py` handlers for `HTTPException`, `RequestValidationError`, and `Exception`
returning `{"error": {"code", "message", "request_id", "details"}, "detail": <unchanged>}`;
`app/core/error_codes.py` registry; frontend parser reads `error.*` first. Lifespan: optional
dependency init cannot abort boot; graph migrations run only when `GRAPH_MIGRATIONS_ON_STARTUP`
(unset = on in development/test) and otherwise via `scripts/run_graph_migrations.py`,
`make migrate-graph`, and the deploy script. Config split into `app/core/settings/*.py`, each
under 500 lines, with `app.core.config` re-exporting the same names.

### R04-07 and R04-06 — Rate limiting and usage writes (D1)

One Lua sliding-window script (Redis `TIME`, hash-tagged keys, user and organisation counters,
check before increment) behind `app/rate_limit/sliding_window.py`, used by all five limiters;
`RATE_LIMIT_ORG_ENABLED`, `RATE_LIMIT_ORG_LIMIT_MULTIPLIER` (10). API-key and service-account
`last_used` go to Redis through a monotonic touch script and a dirty set; `usage.touch.flush`
(every `USAGE_TOUCH_FLUSH_INTERVAL_SECONDS`, 60) pops atomically and writes a max-guarded
`UPDATE`, re-buffering on database failure. Redis down: the touch is dropped and counted.

### R04-05 — Application cache (D2)

`app/core/cache.py` (`get_or_load`, Pydantic `TypeAdapter`, in-process single-flight, versioned
keys `rudix:{env}:org:{org}:v{n}:{ns}:{id}` and `rudix:{env}:user:{user}:v{n}:{ns}:{id}`,
version read before load, missing version initialised from a millisecond clock). Invalidation is
recorded from ORM flushes and explicit repository calls and executed in `after_commit` through
`sqlalchemy.util.await_only`, so `commit()` returns after Redis is updated. Namespaces: auth
principal snapshot, permission sets, feature flags. `CACHE_ENABLED` kill switch.

## 6. Deferred

- Conversion of `usage_events`, `audit_logs`, `authorization_decision_logs`,
  `activity_timeline_events`, `webhook_deliveries` to partitions: needs a staging-volume
  rehearsal, a maintenance window, and a primary key that includes `created_at`. The tooling
  ships now.
- `strict` RLS as default, `FORCE ROW LEVEL SECURITY`, tenant binding on WebSocket and worker
  sessions, and the full F144 suite under the probe role: `0.5.0` (`R05-01` rewrites the chat
  transport).
- RLS on child tables without `organization_id` (`chat_messages`, `citations`,
  `document_chunks`, `document_pages`): needs a backfilled column; `R06-09` adds it to chunks.
- Cache namespaces for AI policy, RAG/model profiles, tool and quota policy: `0.5.0`.
- `AsyncQdrantClient` (`R06-07`) and the outbox table for document processing and webhooks
  (`R06-01`).
- Error-code migration per router and handler refactors of `auth.py` and `agent_runs.py`.
- SQL aggregation for the usage dashboard; a citation `position` column.
- Staging `pg_stat_statements` review for further foreign-key indexes.

## 7. Verification for the release

Run on the merged tree:

```bash
cd backend && make check-revisions && make lint && make test && make test-cov
cd backend && TEST_DATABASE_URL=postgresql+asyncpg://rudix:rudix@127.0.0.1:55432/rudix_test make test-postgres
cd backend && DATABASE_URL=<rudix_test_migrations url> .venv/bin/alembic downgrade 20261126_0001 \
  && DATABASE_URL=<same> .venv/bin/alembic upgrade head
cd backend && .venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json
cd frontend && npm run typecheck && npm run lint && npm run test:coverage && npm run build
cd frontend && npm run test:e2e
```

Coverage must stay at or above the ratchets (backend 76.0, frontend lines 64.8). If a
generated OpenAPI file is stale, regenerate it once on the merged tree.

## 8. Manual steps (staging and production)

1. Run `deploy/sql/provision_roles.sql`, set `DATABASE_URL` to `rudix_app`,
   `DATABASE_MIGRATION_URL` to the owner, `DATABASE_MAINTENANCE_URL` to `rudix_maintenance`.
2. Set `RLS_ENFORCEMENT=soft`; watch `rudix_rls_soft_denials_total` for one week (exit
   criterion). Set `DB_STATEMENT_TIMEOUT_MS` (API, suggested 30000) and
   `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` (suggested 60000).
3. Run the index migrations during low traffic; check for invalid indexes afterwards.
4. Run the `requires_redis` lane in CI to execute the Lua scripts against Redis 7.
5. Run the load baseline (`R03-09`): pool timeouts, page 1 vs page 500, warm-cache auth latency.
6. Rehearse `scripts/partition_table.py` on a staging copy before any conversion is scheduled.

## 9. Change Notes

- 2026-11-27: Initial version, written after checking the `0.4.0` spec against the code at
  `f9d432b`.
