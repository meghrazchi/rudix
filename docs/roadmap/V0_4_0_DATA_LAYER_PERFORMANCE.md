# v0.4.0 — Data Layer Performance

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Draft
- `Last Updated`: 2026-11-26
- `Related Docs`: [../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](../26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md),
  [../06_DATABASE_SCHEMA.md](../06_DATABASE_SCHEMA.md),
  [../22_AUTHORIZATION_SYSTEM.md](../22_AUTHORIZATION_SYSTEM.md)

## 1. Purpose

Make the database and request path efficient and safe for many tenants: configurable pooling,
the right indexes, no N+1 queries, a cache for hot reads, database-enforced tenant isolation,
and bounded table growth.

## 2. Work items

### R04-01 — Engine and pool configuration (S)

- **Change:** Add settings `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`,
  `DB_STATEMENT_TIMEOUT_MS`, and `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS`. Apply the two timeouts
  through `connect_args` server settings. Call `engine.dispose()` in lifespan shutdown. Add
  `DB_PGBOUNCER_MODE`, which disables the asyncpg prepared-statement cache for transaction
  pooling.
- **Rule:** A request MUST NOT hold a connection while awaiting an LLM, embedding, or other
  network call. `R05-02` applies this to chat; apply it here to every other handler found by
  grepping for provider calls inside a session scope.
- **Done when:** Pool gauges (`in_use`, `overflow`, `wait_seconds`) are exported and the
  load test shows no pool timeouts at the target concurrency.

### R04-02 — Index migration (M)

- **Change:** One migration per table group, each using `CREATE INDEX CONCURRENTLY` outside a
  transaction.
  - `(organization_id, created_at DESC)` on `chat_sessions`, `activity_timeline_events`,
    `chat_shares`, `notifications`.
  - `organization_members(user_id)`, `citations(document_id)`, `citations(chunk_id)`,
    `citations(message_id)`, `external_items(connection_id)`,
    `connector_sync_runs(connection_id)`, `source_documents(document_id)`,
    `evaluation_results(evaluation_question_id)`, `usage_events(user_id, created_at)`,
    `audit_logs(user_id, created_at)`.
  - Review the remaining unindexed foreign keys against `pg_stat_statements` from staging and
    add only those that appear in slow queries.
- **Done when:** A Postgres-lane test asserts `EXPLAIN` uses an index for the ten most
  frequent queries, and a test fails when a new foreign key is added without an index or an
  explicit exemption.
- **Rollback:** Drop the indexes; no data change.

### R04-03 — Remove N+1 queries (M)

- **Change:**
  - Message list: load citations for all messages with one `IN` query, or `selectinload`.
  - Collections, documents, connectors, evaluation sets: replace per-row counts with one
    grouped query joined to the page of rows.
  - `app/auth/dependencies.py:384`: fetch documents by ID list in one query.
  - Citation inserts: one bulk insert per answer.
- **Guard:** Add a test helper that counts statements per request and assert an upper bound
  on the fixed endpoints.
- **Done when:** Each listed endpoint issues a constant number of queries regardless of page
  size.

### R04-04 — Keyset pagination (M)

- **Change:** Add an optional `cursor` parameter and a `next_cursor` response field to list
  endpoints over growing tables: chat messages, sessions, documents, notifications, audit
  logs, usage events, activity timeline, webhook deliveries. Cursors encode
  `(created_at, id)`. `offset` keeps working (backward compatible).
  - Replace exact `COUNT(*)` on these endpoints with an optional `include_total` flag.
  - Stream the two large exports (`admin.py:725`, `:1227`) with a server-side cursor instead
    of loading up to 50,000 rows.
- **Done when:** `docs/07_API_DESIGN.md` documents the cursor contract and the load test shows
  flat latency on page 1 and page 500.

### R04-05 — Application cache (L)

- **Problem:** Redis is used only for rate limiting. Auth context, permissions, feature flags,
  AI policy, RAG profile, model profile, tool policy, and quota policy are read from Postgres
  on every request.
- **Change:** Add `app/core/cache.py` with `get_or_load(key, ttl, loader)`, JSON
  serialisation through Pydantic, and single-flight to prevent stampedes.
  - Key shape: `rudix:{env}:org:{org_id}:v{org_version}:{namespace}:{id}`.
  - Invalidation: every write path that changes cached configuration increments
    `org_version` for that organisation. Old keys expire by TTL.
  - TTLs are settings. Suggested: flags and policies 60 s, profiles 300 s, permission sets
    30 s, auth session 30 s.
  - Session revocation, role change, and member removal MUST invalidate immediately.
  - Cache failure falls back to the database and increments an error counter.
- **Done when:** Authenticated request overhead drops from about 4 queries to at most 1 on a
  warm cache, and a test proves a revoked session is rejected on the next request.

### R04-06 — Batched usage writes for API keys and service accounts (S)

- **Change:** Replace the per-request `last_used` and usage row writes with a Redis counter
  flushed by a beat task every minute.
- **Done when:** An API-key request issues no write on the request path.

### R04-07 — Atomic rate limiting (S)

- **Change:** Replace `INCR` + `EXPIRE` + `TTL` with one Lua script implementing a sliding
  window. Add an organisation-level aggregate limit next to the per-user one so one tenant
  cannot consume all capacity.
- **Done when:** One Redis round trip per check, and a test covers the organisation limit.

### R04-08 — Enforce tenant isolation in the database (L)

- **Problem:** The RLS migration exists but `set_postgres_tenant_context` is never called,
  the policy passes when the setting is NULL, and the ORM guard is not enforced.
- **Change:**
  - In the session dependency, run `SET LOCAL app.current_organization_id` at the start of
    each transaction.
  - Add `RLS_ENFORCEMENT=off|soft|strict`. `soft` logs queries that would be denied.
    `strict` makes the policy deny when the setting is NULL and applies
    `FORCE ROW LEVEL SECURITY`.
  - The application connects as a role that is not the table owner and is not a superuser.
    Migrations and workers that legitimately cross tenants use a separate role.
  - Pass `enforce_guard=True` to `bind_session_tenant` on request paths.
  - Extend RLS from 12 tables to every table with an `organization_id` column.
- **Rollout:** `soft` in `0.4.0` staging and production, `strict` as default in `0.5.0`.
- **Done when:** The isolation suite (F144) passes on Postgres with `strict`, and a test that
  omits the application filter still returns no cross-tenant rows.

### R04-09 — Partitioning and retention (L)

- **Change:**
  - Convert `usage_events`, `audit_logs`, `authorization_decision_logs`,
    `activity_timeline_events`, and `webhook_deliveries` to monthly range partitions on
    `created_at`. Use create-new, backfill in batches, swap by rename.
  - Add retention settings per table and a beat task that drops expired partitions.
    Audit log retention defaults to "keep" and is organisation-configurable.
  - A beat task creates next month's partition ahead of time and alerts when it is missing.
- **Done when:** Partition pruning is visible in `EXPLAIN` for dashboard queries, and the
  retention task is covered by a test with a frozen clock.
- **Data safety:** The backfill is resumable and the old table is kept for one release.

### R04-10 — Consistent error envelope (M)

- **Change:** Register global handlers for `HTTPException`, `RequestValidationError`, and
  unhandled exceptions that return
  `{"error": {"code", "message", "request_id", "details"}}`. Keep the top-level `detail`
  field as an alias until `1.0.0`. Migrate string `detail=` call sites to error codes by
  router, highest traffic first.
- **Done when:** No response leaks a stack trace, and the frontend error parser reads `code`.

### R04-11 — No blocking calls on the event loop (M)

- **Change:**
  - Wrap boto3 object calls in `asyncio.to_thread` behind the storage client factory.
  - Use `AsyncQdrantClient` for request-path searches (also used in `R06-07`).
  - Wrap Celery `.delay()` in `to_thread`, or publish after commit through an outbox table
    for the paths where a lost message matters (document processing, webhooks).
  - Add GZip middleware for JSON responses over 1 KB.
- **Done when:** A test with an event-loop lag probe shows no stall above 100 ms during
  upload and retrieval.

### R04-12 — Startup and configuration hygiene (M)

- **Change:**
  - Move Neo4j migrations out of lifespan into the migrate job. Optional dependencies must
    not abort boot; they degrade the readiness check instead.
  - Split `app/core/config.py` (1,668 lines) into nested settings modules per area, keeping
    the same environment variable names.
- **Done when:** No settings file exceeds 500 lines and every existing variable still loads.

### R04-13 — Move persistence out of HTTP handlers (L, incremental)

- **Change:** For the five largest routers after `chat.py` (`documents.py`, `auth.py`,
  `agent_runs.py`, `admin.py`, `evaluations.py`), move queries and commits into application
  workflows and repositories. One router per merge request. No behaviour change.
- **Done when:** Those routers contain no `select(` and no `commit()`.

## 3. Exit criteria

- Load test at target concurrency: no pool timeouts, non-LLM read p95 within target.
- RLS in `soft` mode logs zero would-be denials for one week on staging.
- Statement-count guards are in place for the hot endpoints.

## 4. Failure Modes and Recovery

| Failure | Recovery |
|---|---|
| Stale cache after a permission change | Version bump on write; short TTL; kill switch `CACHE_ENABLED=false` |
| RLS denies a legitimate cross-tenant job | `soft` mode surfaces it first; run the job under the maintenance role |
| Partition swap fails midway | Old table is untouched until the rename; rerun the backfill |

## 5. Security Considerations

`R04-08` is the main control. Cached permission data is security-sensitive: never cache across
organisations, and never serve it after a revocation event.

## 6. Observability and Operations

New metrics: pool gauges, `rudix_cache_hits_total` and `_misses_total` by namespace,
`rudix_db_statements_per_request`, `rudix_rls_soft_denials_total`, partition-missing alert.

## 7. Change Notes

- 2026-11-26: Initial version.
