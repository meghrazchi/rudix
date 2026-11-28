# Backend Scaffold (FastAPI)

This folder contains a production-ready backend skeleton for the AI Document Q&A Assistant.

## Includes

- FastAPI app structure with versioned API routers.
- Domain-driven backend structure under `app/domains/*` (admin, auth, chat, documents, evaluations, pipeline).
- Strict environment-based configuration and fail-fast validation.
- SQLAlchemy async database foundation and Alembic scaffold.
- Celery worker scaffold with RabbitMQ/Redis wiring.
- Client scaffolds for Qdrant, MinIO, and ClamAV.
- Privacy-aware product analytics ingestion plus organization-level opt-out and admin-safe summaries.
- Tenant-scoped operational report events and admin report APIs with bounded date ranges, indexed filters, pagination, and content-free payloads.
- Dockerfile for API and worker images.

## Does not include

- Business logic implementation.
- Production secrets.
- Feature-complete domain workflows.

## Quick start

1. Copy root `.env.example` to `.env` and set values.
2. Start stack from repository root:

```bash
docker compose up --build
# or:
make up
```

3. API health and documentation endpoints:

- `GET http://localhost:8000/api/v1/health`
- `GET http://localhost:8000/api/v1/ready`
- `GET http://localhost:8000/api/v1/configz` (sanitized settings snapshot, controlled by `FEATURE_EXPOSE_CONFIG_SNAPSHOT`)
- `GET http://localhost:8000/docs` — Swagger UI (auto-generated from route and Pydantic model definitions)
- `GET http://localhost:8000/redoc` — ReDoc UI
- `GET http://localhost:8000/openapi.json` — Raw OpenAPI 3.1 schema

4. Apply database migrations:

```bash
make migrate
```

5. Optional: seed local development data:

```bash
make seed-dev
```

## Configuration notes

- Root `.env` is set up with `localhost` infra endpoints for host-run API/worker.
- `docker-compose.yml` overrides API/worker connection URLs to Docker service hostnames for container runtime.
- Compose dependency startup uses healthchecks for PostgreSQL, Qdrant, MinIO, RabbitMQ, and Redis.
- The API and worker fail at startup if required configuration is missing or malformed.
- URL-like settings are strictly validated (database, Qdrant, MinIO, RabbitMQ, Redis, auth provider URLs when applicable, and service base URLs).
- App-managed auth is enabled by default (`AUTH_PROVIDER=app`) and uses a signed bearer token.
- Session-hint cookie (R07-09): `APP_AUTH_SESSION_HINT_COOKIE_ENABLED` (default `false`), `APP_AUTH_SESSION_HINT_COOKIE_NAME` (default `rudix_session_hint`) and `APP_AUTH_SESSION_HINT_COOKIE_DOMAIN` (default host-only) add a non-secret `"1"` cookie (`HttpOnly`, refresh-cookie `Secure`/`SameSite`, `Path=/`) set with the refresh cookie on login, refresh and SSO, and cleared on logout, logout-all and refresh `401`/`403` rejections (invalid, revoked or reused token). It grants nothing; the frontend route gate only checks it exists. Code: `app/interfaces/http/auth_cookies.py`.
- With `APP_AUTH_COOKIE_SAME_SITE=none`, `POST /auth/token/refresh` and `POST /auth/logout` reject a missing or foreign `Origin` (not in `CORS_ORIGINS`) with `403 csrf_origin_rejected`; metric `rudix_auth_csrf_origin_rejections_total{endpoint,reason}`. With `lax`/`strict` nothing changes.
- `clerk` auth provider is implemented with JWKS-based JWT verification (signature, issuer, audience, expiry, subject).
- `supabase` provider wiring exists and uses the same JWKS verifier contract, but requires provider-specific JWT settings and full integration validation.
- Dependency clients are initialized through centralized factories (`app/clients/factory.py`) for consistent timeout/retry handling.
- Language-aware RAG is enabled by default (`FEATURE_ENABLE_LANGUAGE_AWARE_RAG=true`) and supports `en`, `de`, `es`, and `fr` for question detection, answer language selection, and document language metadata.
- Startup bootstraps MinIO bucket and Qdrant collection idempotently when enabled (`MINIO_BOOTSTRAP_BUCKET`, `QDRANT_BOOTSTRAP_COLLECTION`).
- Qdrant collection bootstrap validates vector schema (`QDRANT_VECTOR_SIZE`, `QDRANT_DISTANCE`) and fails fast on mismatch.
- Celery uses explicit queues/routes for document processing, deletion, re-indexing, and evaluations.
- Celery tasks use a shared retry policy (`CELERY_TASK_MAX_RETRIES`, backoff, jitter) and structured failure logging.
- Task terminal failures mark related document/evaluation rows as `failed` where applicable.
- Document processing uses an atomic claim (`documents.processing_task_id`), so retries and redeliveries resume instead of skipping; a terminal failure from a task whose claim was taken over does not mark the document `failed`. `documents.process` skips (`status_not_claimable`) documents in `indexed`, `deleted`, `deleting`, `delete_requested`, `quarantined`, `blocked`, or `retained_by_policy` unless `force=True`, and a terminal failure never overwrites a deletion, retention, or DLP-quarantine status with `failed` (it logs `document.processing.failure_status_preserved` and audits `document.task.failure_ignored`). The beat-scheduled `documents.reap_stale` task re-queues documents stuck in `processing` (`DOCUMENT_PROCESSING_STALE_SECONDS`, `DOCUMENT_REAPER_INTERVAL_SECONDS`, `DOCUMENT_REAPER_MAX_ATTEMPTS`, `DOCUMENT_REAPER_BATCH_SIZE`). Its `rudix_documents_reaped_total` counter is emitted in prefork children and is not scraped yet (see the beat-heartbeat note under Scheduled tasks).
- Redis-backed endpoint rate limiting is configurable and disabled by default in development/test (`RATE_LIMIT_DISABLE_IN_DEVELOPMENT`, `RATE_LIMIT_DISABLE_IN_TEST`).
- Connector sync endpoints use connector-specific Redis rate limits (`RATE_LIMIT_CONNECTOR_REQUESTS`) in addition to the shared admin/document scopes.
- The public contact form uses `POST /api/v1/contact`, persists valid
  submissions, and sends email to `CONTACT_RECEIVER_EMAIL` when
  `EMAIL_ENABLED=true`; throttle it with `RATE_LIMIT_CONTACT_REQUESTS`.
- Slack and Microsoft Teams bot ask events use bot-specific Redis rate limits (`RATE_LIMIT_BOT_REQUESTS`) keyed by provider workspace/team and external user.
- Chunking/index metadata is environment-driven (`CHUNK_SIZE_TOKENS`, `CHUNK_OVERLAP_TOKENS`, `DOCUMENT_INDEX_VERSION`, `CHUNKING_STRATEGY`).
- Production retrieval only serves `DOCUMENT_INDEX_VERSION` plus `DOCUMENT_ACTIVE_INDEX_VERSIONS` (CSV, empty by default; `eval-` entries are rejected). List an old version there while reindexing after a version change. `scripts/purge_eval_index_versions.py` reports index versions per organization and purges leftover evaluation `eval-` versions (dry run by default, `--apply` to delete). It exits `2` when inactive non-eval versions exist. See `docs/12_EVALUATION_AND_MONITORING.md`.
- `CHUNKING_STRATEGY` selects the default strategy for all document processing (default: `token_recursive`). Set to `adaptive_hybrid` to enable automatic per-document strategy selection based on file type, OCR status, and structure heuristics.
- Upload malware scanning is environment-driven (`MALWARE_SCAN_*`) and runs before MinIO writes. In staging and production, settings validation fails when `MALWARE_SCAN_ENABLED=true` and `MALWARE_SCAN_CLAMAV_HOST` is a loopback address (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`); the deploy compose files set it to the `clamav` service. Set `MALWARE_SCAN_ENABLED=false` explicitly to run without a scanner.
- Production profile requires `SENTRY_DSN`.
- Sentry runtime settings are environment-driven (`SENTRY_*`), including optional per-env sampling controls.
- Non-production test event endpoint is available at `POST /api/v1/sentry-test` when enabled.
- Structured logging is configured for both API and Celery worker.
- `LOG_FORMAT=auto` emits readable console logs in development and JSON logs in staging/production.
- Database engine settings (R04-01): `DB_POOL_SIZE` (5), `DB_MAX_OVERFLOW` (10), `DB_POOL_TIMEOUT` (30 s), `DB_STATEMENT_TIMEOUT_MS` and `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` (0 = off), `DB_PGBOUNCER_MODE` (false). The defaults keep the previous behaviour. Alembic uses `DATABASE_MIGRATION_URL` when set; `maintenance_session()` (cross-tenant beat tasks) uses `DATABASE_MAINTENANCE_URL` when set. The engine is disposed on API shutdown. Pool metrics: `rudix_db_pool_wait_seconds`, `rudix_db_pool_timeouts_total`.
- Handlers that make a slow network call inside a request (`POST /admin/model-providers/test`, `POST /admin/webhooks/{id}/test`, `POST /admin/sso/test-connection`) commit before the call so the pooled connection is returned while it runs.
- Row-level security (R04-08): `RLS_ENFORCEMENT` is `off`, `soft` (default in staging/production), or `strict` (default in development/test since 0.5.0). `FORCE ROW LEVEL SECURITY` is operator SQL (`deploy/sql/force_rls.sql`, rollback `unforce_rls.sql`, rendered by `scripts/render_force_rls_sql.py`), applied after the role split. Migration `20261127_0004` covers every table with `organization_id` except the user-scoped identity tables (`users`, `organization_members`, `auth_refresh_sessions`); `deploy/sql/provision_roles.sql` creates the `rudix_app` and `rudix_maintenance` roles. PostgreSQL tests prove isolation with a non-owner probe role (`rls_probe_session` fixture, `tests/test_rls_enforcement_pg.py`); set `TEST_MIGRATIONS_DATABASE_URL` to a database that may be downgraded to also run the migration round trip. See `docs/22_AUTHORIZATION_SYSTEM.md` section 11.
- Realtime events (R07-07): `REALTIME_EVENTS_ENABLED` (default `false`) enables
  `GET /events/stream`. `REALTIME_BUFFER_TTL_SECONDS` (120), `REALTIME_BUFFER_MAX_EVENTS`
  (500), `REALTIME_STREAM_KEEPALIVE_SECONDS` (15), `REALTIME_STREAM_MAX_SECONDS` (300),
  `REALTIME_MAX_CONNECTIONS_PER_USER` (5). Events are recorded on the session by an ORM
  `after_flush` observer (`app/application/realtime/observers.py`) plus explicit calls at
  Core `UPDATE` sites, and published to Redis in `after_commit`
  (`app/application/realtime/publisher.py`); workers use a process-local client. The
  per-user cap is an atomic lease semaphore (leases expire a minute after the longest
  stream), and the endpoint commits the request session before streaming so a stream
  holds no database connection. `documents.changed` is recorded once per organisation and
  transaction, so a bulk change publishes one hint.
- Signing-key rotation (R08-11): `APP_AUTH_SECRET_PREVIOUS` (unset by default) is tried after
  `APP_AUTH_SECRET` when verifying access and refresh tokens and the Slack OAuth state; signing
  always uses `APP_AUTH_SECRET`. Startup refuses an empty previous secret or one equal to the
  current. `rudix_auth_token_verified_by_previous_key_total{kind}` counts verifications that
  needed it; remove it when the counter stops growing (at least the access-token TTL, the
  refresh TTL to keep sessions signed in). It is never used for connector credential
  encryption. The snapshot shows only `infrastructure.app_auth_secret_previous_set`. Runbook:
  `docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` `### Rotation`.

## Settings layout and startup behavior

- `app/core/config.py` holds the `Settings` class, validation, and `settings`/`get_settings`. The fields live in per-area mixins under `app/core/settings/` (`app.py`, `database.py`, `redis_rate_limit.py`, `storage.py`, `celery.py`, `auth.py`, `ai_providers.py`, `rag.py`, `graph.py`, `mcp.py`, `connectors.py`, `observability.py`, `email_bots.py`, `features.py`); enums are in `enums.py` and the sanitized snapshot in `snapshot.py`. Environment variable names are unchanged and every symbol previously imported from `app.core.config` is still re-exported there. Keep each file under 500 lines.
- Redis, RabbitMQ, and Qdrant are optional at boot: if their init fails the API logs `startup.dependency_unavailable` (dependency and error class) and keeps starting; `/api/v1/ready` reports them down and retries the Redis and Qdrant connection on each probe, so the API recovers without a restart.
- `GRAPH_MIGRATIONS_ON_STARTUP` controls Neo4j graph migrations at API startup. Unset means on in development/test and off in staging/production. In staging/production run `make migrate-graph` (or `python scripts/run_graph_migrations.py`) as part of the migrate step; it is a no-op unless `ENTERPRISE_GRAPH_ENABLED=true` and exits non-zero on failure.
- API errors use one envelope (`error.code`, `error.message`, `error.request_id`, `error.details`) with the legacy `detail` alias; see `docs/07_API_DESIGN.md`.

## Authentication quick check

Generate a local app token:

```bash
cd backend
.venv/bin/python - <<'PY'
from app.auth.token_codec import create_app_access_token
print(create_app_access_token(subject="admin", expires_in_seconds=3600))
PY
```

Seeded local dev login:

- email: `admin@example.com`
- password: `123123123`

Password login does not create unknown users by default. For local experiments,
enable `APP_AUTH_AUTO_PROVISION_USERS=true`; staging and production force it off.

Optional: fetch seeded organization UUID (`make seed-dev`):

```bash
ORG_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from organizations where slug='demo-org' limit 1;")
```

Call a protected endpoint:

```bash
TOKEN="<paste_token>"
curl -i http://localhost:8000/api/v1/pipeline/steps \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: ${ORG_ID:-<org_uuid>}"
```

Current endpoint authorization:

- `pipeline/*`: any authenticated org member role (`owner|admin|member|viewer`)
- `agent/runs*`: any authenticated org member role (`owner|admin|member|viewer`) when `FEATURE_ENABLE_AGENTS=true`
- `documents/upload` and `documents/upload-url`: `owner|admin|member`
- `evaluations` (POST): `owner|admin`
- `admin/usage`, `admin/audit-logs`, `admin/audit-logs/export`, and `admin/governance`: `owner|admin`
- `admin/portability/*`: `owner|admin`; creates sanitized workspace export/import jobs and downloadable JSON artifacts
- `admin/bots/*`: `owner|admin`
- `contact`: public validated contact/demo submission endpoint; stores valid
  submissions and dispatches email to the configured receiver
- `status`: public-safe snapshot endpoint with no auth; uses `PUBLIC_STATUS_ORGANIZATION_SLUG` when configured to source incidents from the public Rudix status org
- `bots/slack/events` and `bots/teams/events`: public transport endpoints guarded by Slack signatures or Teams bearer secret when configured.
- `documents/{document_id}`, `chat` `document_ids`, and `evaluations.document_id` are org-scoped; cross-org lookups return `404`.
- Retrieval-side qdrant filters must include `organization_id` (see `app/domains/documents/services/qdrant_filters.py`).

## DDD layout

- `app/interfaces/http`: FastAPI transport adapters (routes/controllers) organized by domain.
- `app/domains/<domain>/repositories`: persistence adapters used by the domain/application logic.
- `app/domains/<domain>/services`: domain/application services for business workflows.
- `app/domains/<domain>/schemas`: transport DTOs for API request/response contracts.
- `app/application`: cross-domain application orchestration and use-case services.
- `app/shared`: cross-domain shared artifacts (for example health schemas).
- `app/api/router.py`: top-level composition root wiring domain routers.

Persistence lives in repositories and application workflows, not in routers:
`tests/test_router_persistence_guard.py` fails if `documents.py`, `admin.py`, or
`evaluations.py` contain `select(` or `.commit(`. `auth.py` (auth-critical) and
`agent_runs.py` (agent execution moves to workers in R06-13) are deferred.

Request paths must not block the event loop: use `app.clients.object_storage` (async
wrappers over the boto3 client) and `app.workers.dispatch.enqueue` (Celery `.delay` in a
thread). Workers keep the sync clients. Deferred: the Celery outbox (R06-01) and
`AsyncQdrantClient` (R06-07); retrieval currently offloads the sync Qdrant call with
`asyncio.to_thread`.

Legacy horizontal layers (`app/services`, `app/repositories`, `app/schemas`) were removed in favor of domain-local modules.

## Agentic core (F98) notes

- Agent feature rollout is environment-driven:
  - `FEATURE_ENABLE_AGENTS`
  - `AGENT_MAX_STEPS`
  - `AGENT_MAX_PARALLEL_TOOL_CALLS`
  - `AGENT_TOOL_MAX_CALLS_PER_RUN`
  - `AGENT_TOOL_TIMEOUT_MS`
  - `AGENT_TOOL_MAX_INPUT_BYTES`
  - `AGENT_TOOL_MAX_OUTPUT_BYTES`
  - `AGENT_TOOL_MAX_RETRY_ATTEMPTS`
- Agent contracts are defined under `app/domains/agents` using `ToolSpec`, `ToolCall`, and `ToolResult`.
- Internal execution is shared through `ToolRegistry` (allowlist) and `AgentToolExecutor` (auth/budget/timeout/audit wrappers).
- `AgentRuntime` provides a persisted plan-act-observe loop with:
  - structured tool selection (`PlannedToolSelection`)
  - runtime budgets (steps/runtime/tool calls/tokens/cost)
  - step persistence in `agent_steps`
  - cancellation checks and safe failure completion
  - final outcome envelope (answer/citations/confidence)
- Read-only document intelligence handlers are implemented in `DocumentIntelligenceToolService` and include:
  - `search_documents`
  - `get_document_detail`
  - `list_document_chunks`
  - `answer_from_context`
  - `summarize_document`
  - `compare_documents`
- Agent trace persistence uses `agent_runs`, `agent_steps`, `agent_tool_calls`, and `agent_approvals`.
- Side-effect tools require idempotency keys and should remain API-only unless explicitly approved for another surface.
- API and MCP adapters must share the same policy checks: role authorization, organization isolation, budgets, and safe output redaction.

## Standalone MCP server (F107)

Rudix now includes a standalone MCP server module under `app/mcp`.

Key behavior:

- MCP is disabled by default via `FEATURE_ENABLE_MCP=false`.
- MCP is a separate adapter surface and does not route through `app.main`.
- Only read-only tools are exposed by default.
- Public MCP tool names are:
  - `search_documents`
  - `ask_documents`
  - `get_document_chunks`
  - `summarize`
  - `compare`
- Compatibility aliases are preserved (`answer_from_context`,
  `list_document_chunks`, `summarize_document`, `compare_documents`,
  `get_document_detail`).
- Read-only MCP resources/templates are exposed for document metadata, status,
  chunks, search context, and citations.
- Provider-neutral MCP prompt workflow templates are also exposed:
  - `grounded_qa`
  - `summarize_workflow`
  - `compare_workflow`
  - `obligations_action_items`
  - `evidence_lookup`
- Prompt templates are parameterized (query/document_ids/style/output_format) and
  enforce the same MCP auth, capability, and rate-limit boundaries.
- Tool execution reuses the shared `ToolRegistry` + `AgentToolExecutor` contract.
- Authorization, organization isolation, budget checks, and redaction rules are enforced identically for API and MCP surfaces.

## Connector credentials (F239)

Connector OAuth/API credentials are stored behind a credential vault boundary:

- Raw access tokens, refresh tokens, API tokens, client secrets, and service-account secrets are encrypted in `connector_credentials`.
- `connector_connections.auth_config` contains safe metadata only: credential ID/version, status, fingerprint, scopes, key ID, and expiry.
- OAuth state is stored hashed in `connector_oauth_states`; callback state is single-use and TTL-bound.
- Token refresh, disconnect/revoke, and diagnostics are shared across OAuth providers through connector domain services.
- Disconnect marks the connection revoked, revokes remote tokens when possible, disables sync jobs, and records audit events.
- Connector detail responses include source permission snapshots for access-review UI hooks; source ACL data is sanitized before exposure.
- Connector observability is available at `GET /api/v1/admin/connectors/health`
  for owner/admin operators and reports provider-specific sync, retry, skip,
  ingestion, and citation signals.
- Connector rollout is controlled through `FEATURE_ENABLE_CONNECTORS` and
  `CONNECTOR_ROLLOUT_STAGE` (`off`, `development`, `staging`, `production`,
  `all`).

Relevant settings:

- `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY`
- `CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_ID`
- `CONNECTOR_OAUTH_STATE_TTL_SECONDS`
- `CONNECTOR_OAUTH_CLIENTS`
- `FEATURE_ENABLE_CONNECTORS`
- `CONNECTOR_ROLLOUT_STAGE`

## Collaboration bots (F261)

Slack and Microsoft Teams bot access is implemented as thin HTTP transport
adapters around the existing Rudix chat query path.

Full setup and local testing guide:
`docs/20_COLLABORATION_BOT_INTEGRATION.md`.

Key behavior:

- Bot feature rollout is controlled by `FEATURE_ENABLE_COLLABORATION_BOTS`.
- Slack OAuth installation starts at `POST /api/v1/admin/bots/slack/oauth/start`
  and completes at `/api/v1/bots/slack/oauth/callback`.
- Admins manage installations with `GET|POST|PATCH /api/v1/admin/bots/installations`.
- Admins can rotate encrypted platform bot tokens with `PUT /api/v1/admin/bots/installations/{installation_id}/credential`.
- Admins map external Slack/Teams users with `PUT /api/v1/admin/bots/installations/{installation_id}/mappings`.
- Ask events arrive at `POST /api/v1/bots/slack/events` or `POST /api/v1/bots/teams/events`.
- Slack request signatures are verified when `BOT_SLACK_SIGNING_SECRET` is set.
- Teams requests require `Authorization: Bearer <secret>` when `BOT_TEAMS_SHARED_SECRET` is set.
- Public bot events acknowledge quickly by default, then post final answers back
  to Slack `response_url`, Slack thread, or Teams conversation where delivery
  credentials are configured. Use `X-Rudix-Bot-Sync: true` for local curl tests
  that should return the answer directly.
- External users must be mapped to active Rudix users in the same organization before asking questions.
- Bot queries use the mapped Rudix user's organization and role context, then reuse existing source-scope, document-access, retrieval, citation, usage, and audit services.
- Bot citations render as Rudix document links only; connector deep links and ACL snapshots are not sent to Slack or Teams responses.
- Safe bot states include empty question, disabled installation, unmapped user, inactive user, rate-limited, and query failure.

Relevant settings:

- `FEATURE_ENABLE_COLLABORATION_BOTS`
- `BOT_SLACK_SIGNING_SECRET`
- `BOT_SLACK_CLIENT_ID`
- `BOT_SLACK_CLIENT_SECRET`
- `BOT_SLACK_OAUTH_REDIRECT_URI`
- `BOT_SLACK_OAUTH_SCOPES`
- `BOT_TEAMS_SHARED_SECRET`
- `BOT_PROCESS_EVENTS_ASYNC`
- `BOT_DELIVERY_TIMEOUT_SECONDS`
- `RATE_LIMIT_BOT_REQUESTS`

## Standalone MCP server runtime

Supported transports:

- `streamable_http` (recommended for deployment)
- `stdio` (development/test only)

Relevant settings:

- `FEATURE_ENABLE_MCP`
- `MCP_SERVER_NAME`
- `MCP_TRANSPORT`
- `MCP_HTTP_HOST`
- `MCP_HTTP_PORT`
- `MCP_HTTP_PATH`
- `MCP_REQUIRE_BEARER_AUTH`
- `MCP_DEV_PRINCIPAL_USER_ID`
- `MCP_DEV_PRINCIPAL_ORGANIZATION_ID`
- `MCP_DEV_PRINCIPAL_ROLES`
- `MCP_CAPABILITIES_OWNER`
- `MCP_CAPABILITIES_ADMIN`
- `MCP_CAPABILITIES_MEMBER`
- `MCP_CAPABILITIES_VIEWER`
- `MCP_RATE_LIMIT_ENABLED`
- `MCP_RATE_LIMIT_WINDOW_SECONDS`
- `MCP_RATE_LIMIT_REQUESTS`
- `FEATURE_ENABLE_EXTERNAL_MCP_CONNECTORS`
- `MCP_EXTERNAL_SERVERS`

Security defaults:

- Bearer auth is required by default for `streamable_http`.
- `MCP_REQUIRE_BEARER_AUTH=false` is intended for development/test only and requires a configured dev principal.
- MCP capability enforcement is role-scoped and least-privilege by default (viewer excludes `chat.answer`).

Run locally from `backend/`:

```bash
make run-mcp-http
# or
make run-mcp-stdio
```

Standalone MCP health endpoints (HTTP mode):

- `GET http://localhost:8010/health`
- `GET http://localhost:8010/ready`

The MCP protocol endpoint defaults to:

- `POST/GET http://localhost:8010/mcp`

Default MCP resource/template URIs:

- `rudix://documents{?status,sort_by,sort_order,limit,offset,query}`
- `rudix://documents/{document_id}`
- `rudix://documents/{document_id}/status`
- `rudix://documents/{document_id}/chunks{?limit,offset}`
- `rudix://search/{query}{?status,sort_by,sort_order,limit,offset}`
- `rudix://citations/{query}{?document_id,top_k,rerank}`

Resource payload policy:

- Responses are intentionally compact for model context efficiency.
- Resource pagination is capped server-side (`limit` is clamped to max 50).
- Citation/snippet text is truncated to concise preview length.

### External MCP connector for agent runtime (F112)

Rudix agents can register approved external MCP tools into the shared internal
`ToolRegistry` when explicitly enabled.

- Disabled by default via `FEATURE_ENABLE_EXTERNAL_MCP_CONNECTORS=false`.
- Server registry is environment-driven through `MCP_EXTERNAL_SERVERS` (JSON array).
- Tool exposure is allowlist-based (`allow_tools`) and role-scoped (`required_roles`).
- External tools default to side-effect policy unless listed in `read_only_tools`;
  side-effect tools require approval by default.
- Discovery failures or schema drift are handled safely: the run continues without
  registering the broken external server.

Minimal example:

```env
FEATURE_ENABLE_EXTERNAL_MCP_CONNECTORS=true
MCP_EXTERNAL_SERVERS=[{"server_id":"acme_tools","enabled":true,"transport":"streamable_http","base_url":"https://mcp.example.com/mcp","auth_type":"bearer","auth_token":"replace-me","allow_tools":["lookup_customer"],"read_only_tools":["lookup_customer"],"required_roles":["owner","admin"]}]
```

Run via Docker from repository root:

```bash
make up-mcp
make logs-mcp
```

`docker-compose.yml` uses a dedicated `mcp` profile so the service is not started unless explicitly requested.

## OpenAPI schema export

The script `scripts/export_openapi.py` dumps the FastAPI OpenAPI schema to JSON without starting any services. It is used by the frontend type generation pipeline and by the `OpenAPI contract` CI check (R03-10).

```bash
# Write schema to stdout
.venv/bin/python scripts/export_openapi.py

# Write schema to a specific path
.venv/bin/python scripts/export_openapi.py ../frontend/openapi.json

# Check the committed schema; exits 1 and lists added/removed/changed paths and schemas
.venv/bin/python scripts/export_openapi.py --check ../frontend/openapi.json
```

- Required config fields get stub values so pydantic-settings loads without live infrastructure.
- `ENVIRONMENT=development` and `API_PREFIX=/api/v1` are forced before the app is imported, so the export does not depend on the caller's environment.
- `--check` compares parsed JSON, so formatting (the committed file is Prettier-formatted) never causes a failure.
- pydantic-settings still reads `.env` for every other field, so a local `.env` can change `info.title` (`API_NAME`) or `info.version` (`API_VERSION`). CI has no `.env`. `info.version` comes from `settings.api_version`; the release bump script updates it.
- The output depends on the installed FastAPI and Pydantic versions. Export from the environment `make install` creates, as CI does.

To refresh the committed schema and types, run `npm run api:update-schema` in `frontend/`.

## Development commands

```bash
make install
make lint
make test
make run-api
make run-worker              # one worker, every queue (dev)
make run-worker-pool POOL=ingest   # one R06-04 pool: ingest|graph|sync|eval|default
make run-beat
make migrate
make downgrade
make seed-dev
```

`make install` creates a local virtualenv at `backend/.venv` and installs all dependencies there.

Dependencies are locked in `backend/uv.lock` (hashed, produced by [uv](https://docs.astral.sh/uv/)).
`make install` runs `uv sync --frozen --extra dev`, which creates `backend/.venv` and installs
exactly the locked set plus the project in editable mode; it fails if the lock is stale. If uv is
not on `PATH`, the Makefile bootstraps a pinned copy into `backend/.tools` (git-ignored).

- `make lock` re-resolves and rewrites `uv.lock`; `make lock-check` fails if it is out of date.
- `make install-load` also installs the Locust load-test extra.
- `make audit` audits the locked set with `pip-audit --require-hashes`; `make audit-report
  AUDIT_OUTPUT=/abs/path.json` writes a JSON report and does not fail on findings.
- To add or change a dependency: edit `pyproject.toml`, run `make lock`, and commit both files.
- The venv has no `pip`; use `uv pip` or `uv add` if you need ad-hoc installs.

## PostgreSQL integration tests

Most backend tests run against a per-test SQLite database (see
[Test speed and coverage](#test-speed-and-coverage)). Tests that need real PostgreSQL or Redis
behavior (row locks, `ON CONFLICT`, concurrent sessions) carry pytest markers:

- `requires_postgres`: needs a migrated PostgreSQL database at `TEST_DATABASE_URL`.
- `requires_redis`: needs a live Redis instance. The live Lua script test
  (`tests/test_rate_limit_redis_live.py`) also needs `TEST_REDIS_URL`, set in the
  `backend-postgres.yml` CI job.

When `TEST_DATABASE_URL` is unset, `requires_postgres` tests are skipped, so `make test` keeps
working without extra services. Two fixtures in `tests/conftest.py` provide database access:

- `pg_session`: an `AsyncSession` inside an outer transaction that is rolled back at teardown.
  Calls to `commit()` in code under test release a savepoint, so nothing persists.
- `pg_session_factory`: an `async_sessionmaker` whose sessions each use a real connection with
  real commits. Use it for concurrency tests, and delete the rows you create, scoped by a unique
  organization ID.

The fixtures are self-migrating: the session-scoped `pg_migrated_url` fixture runs
`alembic upgrade head` against `TEST_DATABASE_URL` once per pytest session (in a subprocess,
because `alembic/env.py` calls `asyncio.run`) and fails the session with the tail of the
Alembic error output if the upgrade fails. `pg_engine` depends on it and still checks that
`alembic_version` exists. Tests never point at `settings.database_url`.

Run the lane against a throwaway database:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/rudix_test make test-postgres
```

Pass extra pytest flags with `PYTEST_ARGS`, for example
`make test-postgres PYTEST_ARGS="--junitxml=artifacts/backend-postgres-junit.xml"`.

### Running a suite on both dialects

A module marked `both_dialects` runs every test that uses the `db_session` fixture twice:
`[sqlite]` (the per-test SQLite session) and `[postgres]` (a rolled-back session on the
migrated PostgreSQL database, built like `pg_session`). The `[postgres]` parameter carries
`requires_postgres`, so it skips without `TEST_DATABASE_URL` and runs in `make test-postgres`.
Tests in the module that do not use `db_session` are collected once.

To port a suite:

1. Add the marker: `pytestmark = [pytest.mark.isolation, pytest.mark.both_dialects]`.
2. Run it with `TEST_DATABASE_URL` set and fix test-only dialect assumptions: naive vs aware
   datetimes, `ORDER BY` without a tie-breaker, fixed slugs or emails (use `uuid4()` suffixes,
   because concurrency tests commit rows to the shared database), and constraints SQLite does
   not enforce (for example `users.organization_id` is `NOT NULL` in the migrations).
3. Skip SQLite-only assertions on PostgreSQL with a reason; if PostgreSQL exposes a real product
   bug, fix it with a regression test or mark that single case `xfail(strict=True, reason=...)`.
4. Check with `pytest --collect-only` that pure-function tests are not duplicated.

Ported suites: `test_rag_isolation_f144.py`, `test_tenant_isolation_f336.py`,
`test_index_version_isolation.py`, `test_chat_transport_parity.py`, `test_quotas_f154.py`,
`test_quota_atomic.py`, `test_document_processing_claim.py`. `test_tenant_isolation_f336.py`
carries the marker but has no `db_session` tests (it checks the policy engine in memory), so it
gets no `[postgres]` parameters. PostgreSQL full-text search
(`plainto_tsquery`, `ts_rank`) has no SQLite equivalent and is covered by
`test_keyword_retrieval_fts_pg.py`.

CI runs the lane in `.github/workflows/backend-postgres.yml` (check name
`Backend PostgreSQL tests`) with PostgreSQL and Redis service containers, on every push and
pull request. The `backend-alembic` job in `ci.yml` keeps only the migration round trip.

## Test speed and coverage

Wall time of `make test`, measured locally (the "before" runs used a copy of the tree with only
the SQLite branch of `db_session` reverted):

| Fixture design | First measurement (4,580 passed, 96 skipped; shared, loaded machine) | Re-measured at review (4,633 passed, 96 skipped) |
|---|---|---|
| Before: in-memory SQLite and `create_all` (about 118 tables) for every test | 360 s, 344 s | 240 s |
| After: schema template copied per test | 130 s, 110 s | 75 s, 76 s |

Fixture design (`tests/conftest.py`):

- The session-scoped `sqlite_template_db` fixture runs `Base.metadata.create_all` once into a
  template SQLite file, with the same `JSONB`/`TSVECTOR` compile shims as the tests.
- `db_session` copies that file into a fresh per-test directory and opens it with `aiosqlite`
  and `StaticPool`. The connect hook registers `to_tsvector`. Every test still gets its own
  database, so isolation is unchanged and no DDL runs per test.
- `both_dialects` tests on PostgreSQL use a rolled-back session instead (see above).

The API router is mounted once, under `settings.api_prefix` (`/api/v1`), in every environment.
Tests must call versioned paths such as `/api/v1/documents`. Root or `/api/...` paths return
`404`, including in `ENVIRONMENT=test`.

Coverage:

```bash
make test-cov   # pytest --cov=app --cov-report=term; fails below the ratchet
```

`[tool.coverage.report] fail_under` in `pyproject.toml` is the ratchet. It holds the measured
`TOTAL` rounded down to one decimal (76.0 when it was set). The `backend` CI job runs pytest with
`--cov=app`, so pytest-cov enforces it there too. Raise the threshold when coverage rises. Never
lower it without a reason in the merge request.

## Chat pipeline

`POST /api/v1/chat` and the chat WebSocket (`/chat/ws`) run one staged pipeline (R05-01).
Since 0.5.0 (S3) the legacy `query_chat` and `_run_ws_chat_pipeline` bodies are gone: both
functions keep their signatures and only delegate (`transports/http.py`, `transports/ws.py`).
HTTP returns the same responses, rows, and errors as the legacy body did; the WebSocket gained
the stages it lacked (rewriting, packing, grounded verifier, tree search, freshness, OCR,
table, and extraction quality, AI policy checks). Slack/Teams bots answer through
`transports/internal.py` (`run_internal_query`), which binds the installation's tenant first.

`CHAT_PIPELINE_V2` is deprecated: it has no effect, `false` logs one startup warning
(`chat.pipeline_v2_ignored`), and the setting is removed in 0.6.0. Remove it from your `.env`.

Chat routes (`app/interfaces/http/`): `chat.py` keeps `router`, `ws_router`, `POST /chat`
(`query_chat`), `/chat/ws` (`chat_websocket`), and the compatibility names; the other routes are
in `chat_sessions.py` (sessions, stats, message list, the deprecated message create),
`chat_trust.py` (trust metadata), `chat_shares.py` (session shares, `GET /chat/shared/{token}`),
`chat_feedback.py`, and `chat_answer_shares.py` (answer shares, `GET /chat/answer-shared/{token}`).
Each module defines an `APIRouter` without prefix or tags; `chat.router` includes them in the
original registration order, so paths and the OpenAPI document did not change. `chat.py`
re-exports the moved route functions by name.

Database sessions (R05-02): stages 1, 2, and 4 share one read session committed after stage 4;
each lookup in stages 5 to 9 uses its own short session; stage 10 writes in one session with one
commit. HTTP reuses the request session and commits each phase; the WebSocket opens a session
per phase. No connection is held while a model is called. New chat sessions and assistant
messages get their ids at the start of the run and are written only by stage 10. Every session
is tenant-bound with `bind_pipeline_session`.

Modules:

| Module | Contents |
|---|---|
| `app/application/chat/pipeline/pipeline.py` | `ChatPipeline(deps).run(request, principal, transport, emitter, scope, request_id)` returns the finished `ChatContext` |
| `app/application/chat/pipeline/context.py` | `ChatContext`: request, scope, config, retrieval, generation, verification, and persist state |
| `app/application/chat/pipeline/runner.py` | `StageRunner`: stage order, optional per-stage timeouts and run deadline (off), degradation records, background-task cleanup, `rudix_chat_stage_seconds{stage}` |
| `app/application/chat/pipeline/deps.py` | `ChatPipelineDeps` and `default_deps`, the one instance of every chat service |
| `app/application/chat/pipeline/events.py` | `ChatEvent`, `Emitter`, `CollectingEmitter`, activity-step payloads |
| `app/application/chat/pipeline/ledger.py` | `TokenLedger`: query embedding and generation tokens and cost per run |
| `app/application/chat/pipeline/sessions.py` | `ChatSessionScope`; `ShortSessionScope` (read, short, and write phases, R05-02); `SingleSessionScope` (one caller-owned session, tests) |
| `app/application/chat/pipeline/snapshots.py` | plain snapshots of the RAG profile and prompt version read in the read phase |
| `app/application/chat/pipeline/stages/` | one file per stage, helpers in `_*.py` |
| `app/application/chat/transports/http.py` | `run_http_query`: runs the pipeline and builds `ChatQueryResponse` |
| `app/application/chat/transports/ws.py` | `run_ws_query`, `WsEmitter`, and `WsSequence` (one `sequence` counter per connection); run handles and the resume grace window (R05-13) |
| `app/application/chat/transports/resume_buffer.py`, `ws_resume.py` | Redis resume buffer and `chat.resume` (R05-13) |
| `app/domains/chat/services/` | `query_intent_service`, `confidence_calibration`, `trust_metadata_builder`, `trust_records`, `citation_enrichment`, `retrieved_chunk` (moved out of `chat.py`) |

Stages, in the order `query_chat` runs them: `authorize` (quota, document access, source
scope, existing chat session ownership), `guard` (prompt-injection check), `resolve_config` (AI response policy,
answer mode, RAG and model profiles, planner, routing, tools, language), `shortcut`
(pass-through), `rewrite`, `direct_answers` (blocked, scope-inventory, and guidance answers;
these end the run early), `retrieve`, `rerank_pack`, `generate`, `verify` (citations, grounded
verifier, critic and refiner, AI policy post-check, confidence), and `persist` (one
transaction). Authorisation, quota, and document access run before any document text is read.

`app/interfaces/http/chat.py` keeps the names tests and the bot service use (contract 4.2.2 in
`docs/roadmap/V0_5_0_IMPLEMENTATION_PLAN.md`): the service names are the `default_deps`
objects, and `_openai_client`, `SessionLocal`, and `ensure_chat_quota` are read at call time.

Golden transcripts in `tests/fixtures/chat_golden/` hold what each transport answers for 47
scenarios; `tests/test_chat_golden_transcripts.py`, `tests/test_chat_golden_edge_transcripts.py`,
and `tests/test_chat_golden_branch_transcripts.py` (freshness, OCR, table, parent context,
hybrid merge, strict verifier, refiner branches) compare HTTP (ASGI and in-process) and the
WebSocket against them. Re-record only for the reasons in contract 4.2.4:

```bash
CHAT_GOLDEN_UPDATE=1 .venv/bin/pytest tests/test_chat_golden_transcripts.py \
  tests/test_chat_golden_edge_transcripts.py tests/test_chat_golden_branch_transcripts.py
```

- Token streaming (R05-03): the answer is generated with `LLMService.stream_answer`
  (same parsing, retries, fallback, and cost as `generate_answer`). `OpenAIChatProvider` and
  `OpenAICompatibleChatProvider` implement `stream()` (usage from the last chunk; a local
  server that rejects `stream_options` gets one retry without it); other providers send one
  chunk from `complete()`. `AnswerFieldStreamExtractor` (`app/domains/chat/services/answer_stream.py`)
  decodes the JSON `answer` field incrementally, so only answer text streams.
- Events (docs/07 "Chat event protocol"): `generation.started {mode}`, `generation.delta`,
  `generation.replace {text, reason}`, `generation.final` (after citation validation, emitted by
  `stages/_final.py` at the end of `verify`), then `chat.completed`. `CHAT_STREAM_MODE=live`
  (default) or `buffered`; strict verification, blocking AI-policy rules, and tree search always
  buffer (`stages/generate.py`, `resolve_stream_mode`).
- `POST /chat/query/stream` (`transports/sse.py`) is the SSE transport: stages 1-3 run before
  the response starts (same HTTP errors as `POST /chat`), then `id`/`event`/`data` frames.
- Cancellation (`chat.cancel`, SSE disconnect) closes the provider stream and writes a
  `chat.completion.cancelled` usage row (`pipeline/partial_usage.py`); no message, no question
  counted. Metrics: `rudix_chat_ttft_seconds{transport}`, `rudix_chat_stream_cancelled_total{transport}`.
- The CI stub (`ci/stubs/llm_stub.py`) streams answers in 16-character pieces and sends the
  usage chunk when `stream_options.include_usage` is set.
- Auxiliary stages (query rewriting, rerank, conflict detection, grounded verifier, refiner,
  tree search) run on the organisation's resolved `chat` model profile (R05-08), so with
  `LLM_DEFAULT_PROVIDER=local` no stage sends `OPENAI_LLM_MODEL`. A rerank provider or model
  set in the RAG profile still wins; `RERANK_DEFAULT_PROVIDER` applies only to callers
  without a profile. Query embeddings stay on the index's embedding model.
- Every provider call records into the run's token ledger (R05-07): the usage event stores
  the totals and `metadata.token_ledger`, the `tokens` quota records the total, and
  `rudix_chat_tokens_total{stage,kind}` counts them. Reported usage now includes auxiliary
  calls.
- Retrieved text is wrapped in per-request boundary markers in every prompt, the
  untrusted-context rule is added in code, and chunks matching injection patterns are
  flagged, down-ranked (default), or dropped (`CHAT_CONTEXT_INJECTION_ACTION`,
  `CHAT_CONTEXT_INJECTION_DOWNRANK_MULTIPLIER`); see `docs/11` (R05-09). Golden prompt hashes
  are taken with the boundary token normalised.
- Provider resilience (R05-06): `ResilientChatProvider` (`app/domains/ai/providers/resilience.py`)
  wraps every chat provider, from `ProviderFactory.get_chat_provider` and for providers
  injected into `LLMService` (never twice). It holds a circuit breaker per provider and model
  (`LLM_BREAKER_*`; an open breaker raises `BreakerOpenError`, `LLMService` skips its retries
  and uses the profile's fallback provider, or answers `generation_failed`), a stream idle
  timeout (`LLM_STREAM_IDLE_TIMEOUT_SECONDS`), and one slot of the organisation's Redis
  semaphore (`app/rate_limit/concurrency.py`, `LLM_ORG_MAX_CONCURRENT_CALLS`, `0` = off, fails
  open without Redis); a full organisation answers `provider_busy` (HTTP `429`). Cached prompt
  tokens (`ChatCompletionResponse.cached_prompt_tokens`) go into the token ledger. The test
  suite resets the breakers before every test (`tests/conftest.py`).
- Resume (R05-13): WebSocket run events carry `stream_sequence` and, with Redis, are buffered
  by `BufferingEmitter` (`transports/resume_buffer.py`). A dropped socket keeps its run for
  `CHAT_WS_RESUME_GRACE_SECONDS` (`transports/ws.py`, `keep_run_alive_after_drop`);
  `chat.resume` (`transports/ws_resume.py`) replays and follows it, or rebuilds
  `chat.completed` from the stored message. Tests: `tests/test_chat_ws_resume.py`
  (`tests/chat_resume_support.py` drives two connections over one `FakeRedis`) and
  `tests/test_chat_resume_buffer.py` (cap, coalescing, replay edge cases); the breaker and
  semaphore in `tests/test_llm_breaker.py`, `tests/test_llm_cached_tokens.py`, and
  `tests/test_llm_org_concurrency.py`.
  `CHAT_WS_ALLOW_QUERY_TOKEN` defaults to `false`; tests of `?token=` set it in their fixture.
- `requires_redis` lane: `TEST_REDIS_URL=redis://... make test-postgres` also runs the
  semaphore and resume-buffer Lua scripts against a real Redis and compares them with the
  Python reference implementations in `tests/redis_fakes.py`.
- Query embeddings are cached per organisation (`query_embedding`,
  `CHAT_QUERY_EMBEDDING_CACHE_TTL_SECONDS`, R05-05); a hit records a zero-token ledger entry
  and counts `rudix_chat_query_embedding_cache_total{result}`.
- Stage 2 reads (AI policy and collection override, RAG profile, answer prompt version, model
  profile, chat tool policy, quota policy limits) and the verified-answer candidates are
  cached under the organisation scope and invalidated on commit (`app/core/cache_invalidation.py`;
  reads in `pipeline/config_cache.py` and next to their repositories). With Redis down they
  read PostgreSQL.
- Stage 4 (`stages/shortcut.py`, `CHAT_VERIFIED_ANSWER_SHORTCUT_ENABLED=false`) matches
  published verified answers by exact normalised question and checks every citation's read,
  cite, scope, and chunk; it runs in shadow mode (records the result, still generates) until
  the response contract allows an answer without a numeric confidence.
- Latency budget (R05-04): `CHAT_TOTAL_DEADLINE_MS` and `CHAT_STAGE_BUDGET_{REWRITE,GRAPH,
  RERANK,CONFLICT,TREE_SEARCH,VERIFY,REFINE}_MS` (0 = off) degrade optional steps per
  `stages/policies.py`, list them in trust metadata `stage_degradations`, and count
  `rudix_chat_stage_skipped_total{stage,reason}`; strict verification withholds the answer.
  Rerank batches run concurrently (`RERANK_MAX_CONCURRENT_BATCHES`, default 4).
- `CHAT_QUERY_EMBEDDING_PREFETCH_ENABLED` (default `false`) overlaps the original question's
  embedding with configuration resolution; it is off because the embedding would run while
  the read-phase connection is checked out.
- A warm-cache grounded question sends 30 SQL statements (`tests/test_chat_query_count.py`);
  the 12-statement target is not met yet.

## Ingestion pipeline

`documents.process` and `documents.reindex` (R06-01) run the ingestion stages in
`app/workers/ingestion/stages/` in order: `extract` (MinIO read, text extraction, OCR),
`clean_detect` (cleaning, language), `dlp`, `chunk` (pages, chunk rows, table chunks),
`graph_extract` (inline, only when document state is persisted), `embed` (embed and upsert
per `INGEST_EMBED_BATCH_CHUNKS` chunks), `index` (stale point cleanup and count check since
R06-06, connector source references), and `finalize` (the only writer of `indexed` and of the
`document.embedding` usage event, in one transaction with its stage row).

- `app/workers/document_tasks.py` is a compatibility facade: task names, signatures, and
  return values are unchanged, and the module globals tests rebind (`SessionLocal`,
  `_qdrant_service`, `_embedding_service`, `_graph_service`, ...) are read at call time
  through `app/workers/ingestion/deps.py::current_deps()`.
- Run id: the Celery task id that holds the processing claim (`self.request.id`). It
  survives `self.retry` and `acks_late` redelivery, so a retried or redelivered task skips
  completed stages and embed batches. A reaper re-queue or a new upload, reindex, or
  `force` starts a new run. `finalize` writes `indexed` only while
  `documents.processing_task_id` still equals the run's claim (`CLAIM_SUPERSEDED`
  otherwise).
- Stage rows: `document_processing_stages` (status, attempt, lease owner and heartbeat,
  counts-only metrics, error code). A running stage can be taken over once its heartbeat is
  older than `INGEST_STAGE_LEASE_SECONDS` (default 900).
- Artifacts: `document_stage_artifacts` holds the extracted and cleaned pages (one part per
  page, split above `INGEST_ARTIFACT_MAX_PART_BYTES`) and one summary part per embed batch
  (token counts and cost; vectors are dropped after the upsert). A missing artifact re-runs
  the stage that produced it. `finalize` deletes the run's artifacts and older runs' rows;
  a terminal task failure (permanent error, for example a DLP block, or retries exhausted)
  deletes the failed run's artifacts; document deletion removes both.
- Resume keeps document state that skipped stages wrote: the task body marks the graph
  status `pending` on every delivery, and a skipped `graph_extract` writes back the status
  and graph run id it recorded. Embed parts record their batch size; a changed
  `INGEST_EMBED_BATCH_CHUNKS` between deliveries re-embeds every batch instead of skipping
  rows.
- Sessions: every stage opens short sessions; none is open while MinIO, OCR, the
  embedding provider, Qdrant, or Neo4j is called (`tests/test_ingestion_sessions_pg.py`).
- Evaluation re-ingest (`persist_document_state=False`) runs the same stages with the stage
  state in memory (`MemoryStageStore`) and without graph extraction or status writes.
- Tests: `tests/test_ingestion_golden.py` (behaviour fixtures recorded through the
  single-pass worker; `INGESTION_GOLDEN_UPDATE=1` rewrites them),
  `tests/test_ingestion_resume.py` (kill a worker inside each stage, redeliver, assert no
  duplicates), `tests/test_document_tasks_compat.py` (facade names).
- Metric `rudix_ingest_stage_seconds{stage,outcome}` (`app/core/metrics_workers.py`).
- 0.6.0 part 2 (R06-01): `INGEST_PIPELINE_MODE=chain` (default) runs each stage as its own
  task (`documents.ingest.extract` ... `.finalize`, then `documents.graph_extract`) from
  `app/workers/ingestion/tasks.py`; `documents.process` claims and dispatches the first
  incomplete stage (`ingestion/dispatch.py::dispatch_stage`, the task's `apply_async`).
  Extract to chunk use `CELERY_QUEUE_DOCUMENTS_PROCESSING`, embed to finalize
  `CELERY_QUEUE_DOCUMENTS_EMBEDDING`, graph `CELERY_QUEUE_DOCUMENTS_GRAPH`.
  `INGEST_PIPELINE_MODE=inline` keeps the single-task runner for one milestone. The test
  suite defaults to `inline` (`tests/conftest.py`); the chain tests switch to `chain` and run
  Celery eagerly (`tests/ingestion_chain_support.py`).
- Run identity: stage messages carry `run_id` and `claim_token`; a fresh claim gets a new run
  (derived from the claim, so a redelivered `documents.process` reaches the same run), and
  `resume_run_id` (reaper) or `job_id` (failed-job retry) continue an unfinished run. A stage
  task whose claim moved returns `superseded`; a duplicate message finds the row completed
  (dispatches the next stage again) or leased by a live delivery (`lease_held`).
- Graph extraction runs after `finalize` in both modes and never fails the document
  (behaviour change: `ENTITY_EXTRACTION_STRICT_MODE` / `RELATION_EXTRACTION_STRICT_MODE`
  failures set `graph_extraction_status=failed` only).
- Heartbeats refresh `processing_started_at` at each stage start and every
  `INGEST_HEARTBEAT_EVERY_PARTS` parts or embed batches. Failed stage tasks record
  `FailedJob(task_name="documents.process", metadata={"stage", "run_id"})`.
- Request-path dispatch (upload, delete, retry-delete, reindex, graph reindex, OCR retry)
  goes through the transactional outbox (`app/application/outbox.py`, table
  `outbox_messages`); responses are unchanged when publication fails, and `outbox.relay`
  publishes the pending rows.
- Every Celery task binds the tenant of its `organization_id` kwarg (`RudixTask.__call__`,
  `bind_worker_tenant`); document and stage tasks raise `tenant_mismatch` before any write
  for another organisation's document. Runbook: `docs/27_INGESTION_AND_WORKERS_RUNBOOK.md`.
- Agent runs (R06-13): `AGENT_RUN_EXECUTION=inline` (default) runs `POST /agent/runs` in the
  request; `worker` stores the run as `queued` with `request_snapshot`, writes an outbox row
  for `agents.run.execute` (queue `CELERY_QUEUE_AGENTS`, default `default`), and returns
  `201` with `status: queued`. The task (`app/application/agents/worker_execution.py`) takes
  a lease (`AGENT_RUN_LEASE_SECONDS`), rebuilds the principal from the database
  (`principal_revoked` when access is gone), resumes after the last completed step, and
  commits after every step; approval enqueues `agents.run.resume`.
- `app/domains/agents/services/runtime.py` is split into `runtime_context`, `runtime_plan`,
  `runtime_outcome`, `runtime_steps`, `runtime_start`, and `runtime_resume` (each under 500
  lines); `AgentRuntime` keeps every name callers use.
- `GET /agent/runs/{run_id}/stream` is Server-Sent Events (0.5.0 framing) from a Redis
  buffer and pub/sub (`AGENT_STREAM_BUFFER_TTL_SECONDS`), falling back to database polling
  (`AGENT_STREAM_POLL_INTERVAL_MS`). Worker tests: `tests/agent_worker_support.py` (eager
  Celery, `FakeRedis` with `publish`/`pubsub`).
- Bounded memory (R06-02): `extract` streams the object to a temporary file
  (`INGEST_TEMP_DIR`, default the system temp dir; sized reads of
  `INGEST_DOWNLOAD_CHUNK_BYTES`, removed on success and failure) and extracts PDF and TXT
  from that file page by page (`stream_document`, `PdfExtractionStream`; TXT in segments of
  `INGEST_TEXT_SEGMENT_CHARS`). Each page's artifact part is written as it is produced;
  pages below the OCR threshold are held back and written into their slot after OCR. DOCX
  is unchanged (loaded whole). `INGEST_MEMORY_CEILING_MB` documents the design bound and is
  not enforced; later stages still read every page's text (`clean_detect`, `chunk`).
- Embedding reuse and run marker (R06-06): `chunk` no longer deletes points first. `embed`
  reuses vectors found by `(organization_id, embedding_model, chunk_hash)` (one scroll per
  batch, `QdrantService.find_reusable_vectors`; a further scroll for the missing hashes only
  when copies of a text fill the page, up to `EMBEDDING_REUSE_MAX_LOOKUPS`, default 3),
  writes `ingest_run_id` on every point, and
  runs up to `EMBEDDING_MAX_CONCURRENT_BATCHES` batches at once (default 1). `index` then
  deletes the document's points of other runs and verifies the point count
  (`QDRANT_POINT_COUNT_MISMATCH`). Metric `rudix_embedding_cache_hits_total{outcome}`.
- Qdrant clients (R06-07): writes use `AsyncQdrantClient` with
  `QDRANT_WRITE_TIMEOUT_SECONDS` (30), chat retrieval one with
  `QDRANT_SEARCH_TIMEOUT_SECONDS` (unset = `QDRANT_TIMEOUT_SECONDS`), one per event loop,
  closed at API and worker shutdown. The collection and payload indexes are ensured at API
  startup, at worker process start, and by `make migrate-qdrant`
  (`python -m app.clients.qdrant_bootstrap`), not on every upsert or delete; a write that
  finds the collection missing bootstraps it once. Collection tuning (`QDRANT_HNSW_*`,
  `QDRANT_*_ON_DISK*`, `QDRANT_SCALAR_QUANTIZATION`, `QDRANT_QUANTIZATION_*`,
  `QDRANT_SHARD_NUMBER`, `QDRANT_REPLICATION_FACTOR`) defaults to the server defaults and
  applies only when a collection is created. `QDRANT_STORE_PARENT_TEXT=false` omits parent
  text from new points; chat retrieval then reads it from `document_chunks`.

- Connector sync (R06-11): `connectors.sync.run` commits one transaction per provider page
  (items, seen markers, a `documents.process` outbox row per created document, checkpoint,
  counters, heartbeat) and resumes a `running` run from `checkpoint_cursor`. Cancellation is
  checked every `CONNECTOR_SYNC_CANCEL_CHECK_ITEMS` items; Retry-After up to
  `CONNECTOR_SYNC_MAX_INLINE_BACKOFF_SECONDS` is slept in the run, longer ones re-enqueue;
  `CONNECTOR_SYNC_MAX_CONCURRENT_PER_ORG` / `_PER_CONNECTION` cap runs (0 = off). The engine
  facade is `app/domains/connectors/services/sync_engine.py` over `services/sync/`. Details:
  `docs/16_CONNECTOR_PLATFORM.md` (Sync Lifecycle and Checkpoints).
- Chunk tenant column (R06-09): the chunk stage writes `document_chunks.organization_id`,
  `fts_config` (document language: english, german, spanish, french, else simple) and
  `fts_vector`. Older rows: `documents.chunks.backfill_tenant` (reindex queue) or
  `.venv/bin/python scripts/backfill_chunk_tenant.py [--dry-run]`, then the operator SQL
  `deploy/sql/document_chunks_not_null.sql` (rendered by
  `scripts/render_chunk_not_null_sql.py --check`). Until then the table is in
  `RLS_PENDING_TABLES` and the ORM guard does not filter it.
- Keyword search (R06-09): `KEYWORD_SEARCH_MULTILINGUAL` (default `false`),
  `KEYWORD_SEARCH_TENANT_COLUMN` (`auto|on|off`), `KEYWORD_SEARCH_CANDIDATE_LIMIT` (default
  1000, `0` unbounded). The pipeline passes the detected question language. The SQL is in
  `app/domains/chat/services/keyword_search_query.py`.
- Graph writes (R06-10): ingestion writes entities, aliases, evidence and relations with
  `UNWIND` batches (`GRAPH_WRITE_BATCH_SIZE`, default 200), one Neo4j write transaction per
  batch. Extraction LLM batches run with `ENTITY_EXTRACTION_MAX_CONCURRENT_BATCHES` /
  `RELATION_EXTRACTION_MAX_CONCURRENT_BATCHES` (default 1). Single-item graph methods stay
  for the admin endpoints.
- Vector index generations (R06-08): `QDRANT_COLLECTION_ALIAS` unset keeps legacy mode
  (`QDRANT_COLLECTION` directly). With it set, run `.venv/bin/python scripts/vector_index.py
  adopt` once, then `plan`, `build [--enqueue]`, `status`, `swap [--yes]`, `rollback [--yes]`,
  `drop-retired [--yes]` (swap, rollback and drop-retired are dry runs without `--yes`).
  Code: `app/domains/vector_index/`, task `vector_index.build` (reindex queue), beat
  `vector-index-drop-retired` (acts only with `VECTOR_INDEX_AUTO_DROP_RETIRED=true`). A
  changed embedding model or dimension at startup registers a building generation instead
  of failing. Read API: `GET /admin/vector-index/status`. Runbook: docs/27 "Reindex and
  alias swap".
- Evaluation isolation (R06-12): `evaluations.run` lives in `app/workers/evaluation/`
  (`app/workers/evaluation_tasks.py` is the facade tests patch) and runs on the evaluations
  queue (`eval` pool). `QDRANT_EVALUATION_COLLECTION` (unset keeps eval vectors in the
  production collection) sends chunking-comparison re-ingest, eval retrieval, cleanup,
  `scripts/purge_eval_index_versions.py` and the document-deletion cascade to a dedicated
  collection. `EVALUATION_MAX_CONCURRENT_QUESTIONS` (default 1) bounds concurrent
  questions per target; gauge `rudix_evaluation_questions_in_flight`. Runbook: docs/27
  "Evaluation isolation".

## Application cache

`app/core/cache.py` (R04-05) caches small, hot authorization reads in Redis:

```python
value = await get_or_load(
    scope=OrgScope(org_id),          # or UserScope(user_id)
    namespace=NAMESPACE_FEATURE_FLAGS,
    key_id="overrides",
    ttl=settings.cache_ttl_flags_seconds,
    adapter=TypeAdapter(dict[str, bool]),
    loader=load_from_db,
)
```

- Keys are `rudix:{env}:org:{org_id}:v{version}:{namespace}:{id}` and
  `rudix:{env}:user:{user_id}:v{version}:{namespace}:{id}`. The version is read before the
  loader runs and the value is written under that version, so a slow writer can only write an
  orphaned key. Values are Pydantic `TypeAdapter` JSON. Concurrent misses for one key in a
  process run the loader once (single-flight).
- Cached in `0.4.0`: the auth principal snapshot (`AppAuthProvider.authenticate`, user scope,
  keyed by session id), custom-role permission sets (`PermissionService.get_user_permissions`
  with `organization_id`), and organisation feature-flag overrides
  (`FeatureFlagService.is_enabled`). AI policy, RAG/model profiles, tool and quota policy are
  deferred to `0.5.0`.
- Invalidation: `app/core/cache_invalidation.py` installs SQLAlchemy listeners (from
  `app/db/session.py`). ORM writes to `OrganizationMember`, `User`, `CustomRole`,
  `CustomRolePermission`, `OrgFeatureFlagOverride`, and `AuthRefreshSession.revoked_at` are
  picked up in `after_flush`; Core `update()`/`delete()` statements on those tables must call
  `mark_dirty(session, org_ids=..., user_ids=...)`. The version bump runs in `after_commit`,
  so `await session.commit()` returns after Redis is updated; a rollback drops the bumps.
  Savepoints (`begin_nested()`) neither bump on release nor drop the outer transaction's bumps
  on `ROLLBACK TO SAVEPOINT`; only the outermost commit bumps.
- Redis errors, timeouts, a missing client, or `CACHE_ENABLED=false` fall back to the database
  and count `rudix_cache_errors_total`.
- Tests: `tests/redis_fakes.FakeRedis` monkeypatched into `app.clients.redis_client.redis_client`
  (`tests/test_cache_core.py`, `tests/test_cache_invalidation.py`, `tests/test_cache_auth.py`).

| Setting | Default | Meaning |
| --- | --- | --- |
| `CACHE_ENABLED` | `true` | Kill switch; `false` reads every value from the database. |
| `CACHE_TTL_AUTH_SESSION_SECONDS` | `30` | Principal snapshot TTL. |
| `CACHE_TTL_PERMISSIONS_SECONDS` | `30` | Custom-role permission set TTL. |
| `CACHE_TTL_FLAGS_SECONDS` | `60` | Feature-flag override map TTL. |
| `CACHE_TTL_POLICIES_SECONDS` | `60` | Reserved for policy namespaces (`0.5.0`). |
| `CACHE_TTL_PROFILES_SECONDS` | `300` | Reserved for RAG/model profile namespaces (`0.5.0`). |
| `CACHE_OPERATION_TIMEOUT_MS` | `250` | Per Redis operation; on timeout the database is used. |

## Useful task commands

From `backend/`:

```bash
# Worker visibility
.venv/bin/celery -A app.workers.celery_app:celery_app status
.venv/bin/celery -A app.workers.celery_app:celery_app inspect active_queues
.venv/bin/celery -A app.workers.celery_app:celery_app inspect registered
.venv/bin/celery -A app.workers.celery_app:celery_app inspect active
.venv/bin/celery -A app.workers.celery_app:celery_app inspect reserved
.venv/bin/celery -A app.workers.celery_app:celery_app inspect scheduled
```

Every Celery task module must be listed in `include` in `app/workers/celery_app.py`, and every task name must have an explicit `task_routes` entry targeting a declared queue. `tests/test_celery_task_registry.py` enforces both.

Auth/authorization guard checks:

```bash
# Run targeted auth + qdrant filter tests
.venv/bin/pytest tests/test_auth_provider.py tests/test_auth_api.py tests/test_qdrant_filters.py -q

# Run rate-limit tests (unit + API behavior)
.venv/bin/pytest tests/test_rate_limit.py -q

# Build an app token for manual API checks
TOKEN=$(.venv/bin/python - <<'PY'
from app.auth.token_codec import create_app_access_token
print(create_app_access_token(subject="admin", expires_in_seconds=3600))
PY
)

# Resolve seeded organization id (requires `make seed-dev`)
ORG_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from organizations where slug='demo-org' limit 1;")

# Authenticated access succeeds
curl -i http://localhost:8000/api/v1/pipeline/steps \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID"

# Document upload (PDF/TXT/DOCX only)
curl -i http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" \
  -F "file=@/absolute/path/to/sample.pdf;type=application/pdf"

# Upload response should include: "status":"uploaded","queue_status":"queued"

# Fetch document detail (includes processing/indexed/failed status + safe error payload)
DOC_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from documents order by created_at desc limit 1;")
curl -sS http://localhost:8000/api/v1/documents/$DOC_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" | jq

# List documents for active org (pagination + filter + sort)
curl -sS "http://localhost:8000/api/v1/documents?status=indexed&limit=10&offset=0&sort_by=created_at&sort_order=desc" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" | jq

# Fetch compact status payload for polling clients
curl -sS http://localhost:8000/api/v1/documents/$DOC_ID/status \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" | jq

# Fetch paginated chunk previews (safe by default)
curl -sS "http://localhost:8000/api/v1/documents/$DOC_ID/chunks?limit=5&offset=0" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" | jq

# Fetch chunks with full text explicitly enabled
curl -sS "http://localhost:8000/api/v1/documents/$DOC_ID/chunks?limit=2&offset=0&include_full_text=true" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" | jq

# Create a chat session
CHAT_SESSION_ID=$(curl -sS http://localhost:8000/api/v1/chat/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"title":"Policy Q&A"}' | jq -r '.session_id')

# List scoped chat sessions
curl -sS "http://localhost:8000/api/v1/chat/sessions?limit=10&offset=0" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" | jq

# Get one chat session
curl -sS http://localhost:8000/api/v1/chat/sessions/$CHAT_SESSION_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" | jq

# Run main chat query pipeline (POST /chat)
curl -sS http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d "{\"question\":\"What does this document say?\",\"chat_session_id\":\"$CHAT_SESSION_ID\",\"document_ids\":[\"$DOC_ID\"],\"top_k\":5,\"rerank\":true}" | jq

# Run agentic mode (explicit switch + nested runtime request)
AGENT_RUN_ID=$(curl -sS http://localhost:8000/api/v1/agent/runs \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d "{\"agentic_mode\":true,\"request\":{\"objective\":\"Answer policy question\",\"mode\":\"answer\",\"question\":\"What does this document say?\",\"document_ids\":[\"$DOC_ID\"],\"top_k\":5,\"rerank\":true}}" | jq -r '.run.run_id')

# Inspect persisted run trace (run, steps, tool calls, approvals)
curl -sS "http://localhost:8000/api/v1/agent/runs/$AGENT_RUN_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" | jq

# Verify uploaded object exists in MinIO
docker compose run --rm minio-init /bin/sh -lc \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc ls --recursive "local/$MINIO_BUCKET"'

# Verify uploaded row lifecycle metadata in PostgreSQL
docker compose exec -T postgres psql -U postgres -d rag_app -c \
  "select id, organization_id, uploaded_by_user_id, status, file_type, storage_bucket, storage_object_key, checksum from documents order by created_at desc limit 5;"

# Verify background processing task was queued/consumed
docker compose logs --tail=100 worker | rg "document.processing.(started|completed|failed|skipped)"

# Inspect cleaning stats emitted by worker on completion
docker compose logs --tail=200 worker | rg "cleaning_pages_total|cleaning_chars_before|cleaning_chars_after"

# Inspect chunking stats emitted by worker on completion
docker compose logs --tail=200 worker | rg "chunk_count|index_version"

# Inspect embedding stats emitted by worker on completion
docker compose logs --tail=200 worker | rg "embedding_batch_count|embedding_total_tokens|embedding_cost_usd"

# Inspect qdrant upsert stats emitted by worker on completion
docker compose logs --tail=200 worker | rg "qdrant_collection|document.processing.completed"

# Inspect extracted pages (page_number, text, char_count)
DOC_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from documents order by created_at desc limit 1;")
docker compose exec -T postgres psql -U postgres -d rag_app -c \
  "select page_number, char_count, left(text, 120) as preview from document_pages where document_id='${DOC_ID}'::uuid order by page_number;"

# Inspect persisted chunks (chunk_index, page_number, token_count, index_version)
docker compose exec -T postgres psql -U postgres -d rag_app -c \
  "select chunk_index, page_number, token_count, index_version, left(text, 120) as preview from document_chunks where document_id='${DOC_ID}'::uuid order by chunk_index;"

# Inspect embedding usage events (for billing/observability integration)
docker compose exec -T postgres psql -U postgres -d rag_app -c \
  "select event_type, model_name, input_tokens, cost_usd, metadata from usage_events where event_type='document.embedding' order by created_at desc limit 10;"

# Inspect latest pipeline runs for document ingestion
docker compose exec -T postgres psql -U postgres -d rag_app -c \
  "select id, pipeline_type, status, document_id, duration_ms, started_at, completed_at from pipeline_runs order by created_at desc limit 10;"

# Inspect node-level pipeline events for latest run
RUN_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from pipeline_runs order by created_at desc limit 1;")
docker compose exec -T postgres psql -U postgres -d rag_app -c \
  "select sequence, node_name, status, duration_ms, error_message, outputs from pipeline_events where pipeline_run_id='${RUN_ID}'::uuid order by sequence;"

# Inspect persisted qdrant point ids on chunk rows
docker compose exec -T postgres psql -U postgres -d rag_app -c \
  "select chunk_index, qdrant_point_id from document_chunks where document_id='${DOC_ID}'::uuid order by chunk_index;"

# Inspect qdrant payload fields and org/document filterability (requires ORG_ID + DOC_ID)
ORG_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select organization_id from documents where id='${DOC_ID}'::uuid;")
docker compose exec -T qdrant sh -lc "curl -sS -X POST 'http://localhost:6333/collections/documents/points/scroll' \
  -H 'Content-Type: application/json' \
  -d '{\"limit\":3,\"with_payload\":true,\"with_vector\":false,\"filter\":{\"must\":[{\"key\":\"organization_id\",\"match\":{\"value\":\"'\"${ORG_ID}\"'\"}},{\"key\":\"document_id\",\"match\":{\"value\":\"'\"${DOC_ID}\"'\"}}]}}'"

# Cross-org/missing-document-safe behavior
curl -i http://localhost:8000/api/v1/documents/11111111-1111-1111-1111-111111111111 \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID"
```

Dispatch a `documents.process` task with a real UUID:

```bash
DOC_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from documents order by created_at desc limit 1;")
DOC_ID="$DOC_ID" .venv/bin/python -c "import os; from app.workers.document_tasks import process_document; doc=os.environ['DOC_ID'].strip(); r=process_document.delay(doc, force=True); print('doc_id=', doc); print('task_id=', r.id)"
```

Queue cleanup (purges queued, not-started messages):

```bash
.venv/bin/celery -A app.workers.celery_app:celery_app purge -f
```

Notes:

- Never enqueue placeholder values like `PUT_DOC_UUID_HERE` or `<DOC_UUID>`.
- `force=true` does not bypass UUID validation.
- If local and Docker workers run together, either worker may consume tasks.
- Duplicate file uploads are currently accepted and stored as separate document records (each with a unique `document_id` and object key).
- Uploads are malware-scanned before persistence; infected files are rejected with safe `422` responses and are not stored/queued.
- Scanner-unavailable behavior is controlled via `MALWARE_SCAN_REQUIRED` and `MALWARE_SCAN_BYPASS_ON_UNAVAILABLE`.
- Each successful upload immediately enqueues `documents.process`; if enqueue fails, API returns `503` and the document remains in `uploaded` state.
- Worker extraction currently supports PDF (page-by-page via PyMuPDF), TXT (UTF-8 with fallback), and DOCX (paragraphs + tables).
- Worker normalization removes null/control characters, normalizes whitespace/blank lines, and records `cleaning_*` stats in processing logs.
- Worker chunking stores `document_chunks` with deterministic `chunk_index`, `token_count`, `embedding_model`, and `index_version`; current-version chunks are replaced idempotently on reprocessing.
- Chunking strategy is configurable per deployment via `CHUNKING_STRATEGY`. The `adaptive_hybrid` strategy automatically selects `page_aware` (OCR/multi-page PDFs), `heading_aware` (DOCX/Markdown/structured text), `paragraph_recursive` (short articles), or `token_recursive` (fallback) based on document signals. The selected strategy and reason codes are stored in `documents.chunking_config_snapshot` for debugging.
- OCR language overrides accept `en`, `de`, `es`, and `fr` and are stored per document as Tesseract codes after validation.
- Reranking is configurable via `RERANK_DEFAULT_PROVIDER`, `RERANK_DEFAULT_MODEL_NAME`, `RERANK_DEFAULT_TIMEOUT_SECONDS`, `RERANK_DEFAULT_BATCH_SIZE`, `RERANK_DEFAULT_INPUT_CANDIDATES`, `RERANK_DEFAULT_CANDIDATE_CHARS`, `RERANK_DEFAULT_FALLBACK_BEHAVIOR`, `RERANK_INPUT_COST_PER_MILLION_TOKENS_USD`, and `RERANK_OUTPUT_COST_PER_MILLION_TOKENS_USD`. RAG profiles can override the active rerank provider, model, timeout, batch size, candidate limits, and fallback behavior per organization.
- Conflict detection and source-agreement scoring are gated by `FEATURE_ENABLE_CONFLICT_DETECTION` and can be overridden per RAG profile with `conflict_detection_enabled`. When enabled, chat responses expose conflict diagnostics and per-citation conflict status so the UI can warn users when sources disagree.
- Admins can force a specific strategy for all documents by setting `CHUNKING_STRATEGY=<name>`, or for individual documents by passing `force_strategy` in `strategy_options` when using `adaptive_hybrid`.
- Worker embedding generation batches chunk texts, retries transient provider failures with backoff, validates vector dimension, and records `document.embedding` usage events with token/cost metadata.
- Worker qdrant indexing upserts chunk vectors in batches with deterministic point IDs (`{document_id}:{index_version}:{chunk_index}`).
- Qdrant payloads include security and citation fields: `organization_id`, `user_id`, `document_id`, `chunk_id`, `filename`, `file_type`, `page_number`, `chunk_index`, `text`, `embedding_model`, `index_version`.
- Worker marks status transitions `uploaded -> processing -> indexed` and terminal failures as `failed`.
- Failure rows store a safe `error_message` plus structured `error_details` (stage/code/category/retryable/message) for frontend polling.
- Enterprise Graph uses Neo4j as a derived layer only. PostgreSQL remains the
  source of truth, Qdrant remains the vector store, and graph features stay
  gated behind `ENTERPRISE_GRAPH_ENABLED`.
- Member-facing graph explorer reads are available under `/api/v1/graph` for
  organization-scoped entity search and entity detail pages. These routes are
  read-only and return a safe `503` when the graph layer is disabled or Neo4j
  is unavailable.
- Graph-backed chat retrieval is separately gated behind
  `FEATURE_ENABLE_GRAPH_RAG` and uses `GRAPH_RAG_*` settings for hop depth,
  related-entity limits, graph chunk limits, confidence thresholds, and
  relationship allowlists. When Neo4j is unavailable, chat falls back to the
  normal Qdrant path without breaking non-graph functionality.
- Admin graph observability is available under `/api/v1/admin/graph/observability`
  for owner/admin users. It reports extraction health, entity and relation
  quality, GraphRAG query latency, fallback usage, and daily trend snapshots,
  all scoped to the active organization.
- Entity canonicalization is gated behind `FEATURE_ENABLE_ENTITY_RESOLUTION`.
  When enabled, the worker resolves aliases and language variants to canonical
  entity records, stores alias/source mention nodes, and leaves low-confidence
  matches in review state instead of auto-merging them.
- Admin graph review endpoints expose alias inspection plus manual
  merge/split decision recording under `/admin/graph/entity-resolution/*`.
- Relation extraction runs after entity extraction when
  `FEATURE_ENABLE_RELATION_EXTRACTION=true`. Confidence below
  `RELATION_CONFIDENCE_THRESHOLD` is marked `low_confidence`; review mode keeps
  newly extracted relations in `unverified` state until they are approved.

## Scheduled tasks (Celery beat)

Celery beat is the scheduler that enqueues periodic tasks. It schedules these entries (among others) from
`beat_schedule` in `app/workers/celery_app.py`:

- `connector-sync-schedule-poll` (`connectors.sync.schedule_poll`) every
  `CONNECTOR_SYNC_SCHEDULE_POLL_INTERVAL_SECONDS` seconds (default 60).
- `agent-approvals-expire` (`agents.approvals.expire`) every 60 seconds.
- `documents-reap-stale` (`documents.reap_stale`) every `DOCUMENT_REAPER_INTERVAL_SECONDS`
  seconds (default 300).
- `outbox-relay` (`outbox.relay`) every `OUTBOX_RELAY_INTERVAL_SECONDS` seconds (default 5):
  publishes pending `outbox_messages` rows (`OUTBOX_RELAY_BATCH_SIZE`, `FOR UPDATE SKIP
  LOCKED`, backoff, `failed` after `OUTBOX_MAX_ATTEMPTS`). Without it, an upload whose
  immediate publication failed stays `uploaded`.
- `documents-stage-artifacts-purge` (`documents.stage_artifacts.purge`) daily at 04:05 UTC:
  deletes stage artifacts older than `INGEST_STAGE_ARTIFACT_TTL_HOURS` (default 72) of
  documents that are not processing.
- `agents-runs-reap` (`agents.runs.reap`) every `AGENT_RUN_REAP_INTERVAL_SECONDS` seconds
  (default 60): re-queues worker-executed agent runs whose lease expired (`resume_count + 1`)
  and fails them with `worker_lost` after `AGENT_RUN_MAX_RESUMES` (default 3). Runs executed
  inline are never touched.
- `connector-sync-reap` (`connectors.sync.reap`) every `CONNECTOR_SYNC_REAP_INTERVAL_SECONDS`
  seconds (default 120): re-enqueues `running` connector sync runs whose heartbeat is older
  than `CONNECTOR_SYNC_STALE_SECONDS` (default 600), so they resume from their checkpoint.

Without a beat process, scheduled connector syncs, approval expiry, stale-document
recovery, stale connector-sync recovery, and agent run recovery never run.

Worker platform (0.6.0, R06-03 to R06-05): beat schedules nothing new for it. The queue depth
gauges come from a sampler in `worker-default`'s main process
(`WORKER_SAMPLE_QUEUE_DEPTH`, every `WORKER_QUEUE_SAMPLE_INTERVAL_SECONDS`, default 30), not
from a beat task, because a task in a prefork child cannot export metrics on the worker's
metrics port. Beat itself stays a single process outside the pools; its tasks run on the
`default` queue, so `worker-default` must be running for them. Every task, beat tasks
included, now has a soft and a hard time limit (defaults 300 s / 360 s unless
`CELERY_TASK_TIME_LIMITS` names it; `maintenance.retention.purge` 1500 s / 1620 s).

Worker notes:

- `make run-worker` consumes every queue in `task_queues`. Staging and production run five
  pools (`python -m app.workers.pools ingest|graph|sync|eval|default`), each with `-Q`,
  `--concurrency`, and `--pool` from `WORKER_POOL_<NAME>_*` (docs/10 "Worker pools").
- `CELERY_WORKER_MAX_TASKS_PER_CHILD` (200) and `CELERY_WORKER_MAX_MEMORY_PER_CHILD_KB` (0,
  off) recycle children. A time-limited task records `FailedJob.error_code`
  `task_soft_time_limit` or `task_time_limit`.
- `CELERY_QUEUE_TYPE=quorum` switches to quorum queues with a dead-letter exchange; follow the
  cut-over in docs/27 (new queue names, drain the old ones).

Document processing claim and stale reaper: `documents.process` and `documents.reindex`
atomically claim the document by writing their Celery task ID to
`documents.processing_task_id` (with `processing_started_at`). A Celery autoretry or an
`acks_late` redelivery after a worker crash keeps the same task ID, so it re-enters its own
claim and finishes; a different task that finds a live claim logs `claim_held` and skips. `documents.process` also skips documents in `deleting`, `delete_requested`, `quarantined`, `blocked`, or `retained_by_policy` (`status_not_claimable`), and terminal failure leaves those statuses (and `deleted`) untouched, clearing only the task's own claim columns. The
reaper treats a `processing` document as stale once `processing_started_at` (or `updated_at`
for rows without a claim) is older than `DOCUMENT_PROCESSING_STALE_SECONDS` (default 3600). It
releases the claim and re-queues `documents.process` (with `resume_run_id` = the latest
unfinished run, so completed stages are not repeated), at most `DOCUMENT_REAPER_MAX_ATTEMPTS`
times (default 3; `DOCUMENT_REAPER_BATCH_SIZE` rows per run), and then marks the document
`failed` with error code `PROCESSING_STALLED`. Set the stale threshold above the longest
expected processing time, or the reaper re-queues documents that are still running (the claim,
the unique chunk constraint, and deterministic Qdrant point IDs prevent duplicate chunks or
vectors, but the work is repeated). A stalled reindex is re-queued as `documents.process` with
the default chunking profile. The exit criterion "a document survives a forced worker kill
during processing and reaches `indexed`" is verified on staging after deploy; it cannot be run
in CI.

Run exactly one beat instance per deployment. Never scale it: duplicate beats double-schedule
every task.

- Locally: `make run-beat` (from `backend/`).
- Docker Compose: the `beat` service exists in the root, staging, production, and integration
  compose files, so `make up` starts it.
- The schedule file is written to `/tmp/celerybeat-schedule` inside the container. It is
  ephemeral, which is fine because all entries are interval schedules.

Verify with `docker compose logs beat`. You should see `beat: Starting...` and, within one
interval, `Scheduler: Sending due task connector-sync-schedule-poll`. Interval entries first
fire one interval after startup.

A beat heartbeat alert is planned for `0.8.0`. It depends on worker task counters being
exported from prefork child processes, which is not the case yet.

Credential usage flush (R04-06): beat also schedules `usage-touch-flush`
(`usage.touch.flush`, default queue) every `USAGE_TOUCH_FLUSH_INTERVAL_SECONDS` seconds
(default 60, range 10 to 3600). API-key and service-account requests buffer `last_used_at` and
`last_used_ip` in Redis instead of updating the row; the task pops up to
`USAGE_TOUCH_FLUSH_BATCH_SIZE` credentials (default 500) per batch and writes a bulk `UPDATE`
that never moves `last_used_at` backwards. Without beat, the admin pages keep showing the last
flushed value.

| Setting | Default | Effect |
| --- | --- | --- |
| `RATE_LIMIT_ORG_ENABLED` | `true` | Organisation aggregate rate limit for HTTP and WebSocket scopes. |
| `RATE_LIMIT_ORG_LIMIT_MULTIPLIER` | `10` | Organisation limit = scope limit x multiplier, per scope and endpoint. |
| `USAGE_TOUCH_FLUSH_INTERVAL_SECONDS` | `60` | Beat interval of `usage.touch.flush`. |
| `USAGE_TOUCH_FLUSH_BATCH_SIZE` | `500` | Credentials popped from Redis per flush batch. |

Rate limits use one Lua sliding-window script per check (one Redis round trip); see
`docs/11_SECURITY_AND_PRODUCTION_CHECKLIST.md` `## Rate limiting`. The live script test runs
only with `TEST_REDIS_URL` set: `TEST_REDIS_URL=redis://localhost:6379/15 .venv/bin/pytest
tests/test_rate_limit_redis_live.py`.

Retention and partitions (R04-09): beat schedules `maintenance.retention.purge` daily at 03:15
UTC and `maintenance.partitions.ensure` daily at 03:45 UTC (default queue, maintenance
session). Every retention window defaults to keep. Details are in
`docs/06_DATABASE_SCHEMA.md` `## Retention and partitioning`.

| Setting | Default | Effect |
| --- | --- | --- |
| `RETENTION_USAGE_EVENTS_DAYS` | unset (keep) | Delete usage events older than N days (min 7). Usage events feed quotas and invoices. |
| `RETENTION_AUDIT_LOGS_DAYS` | unset (keep) | Platform audit retention (min 30); an organisation override in `PATCH /admin/governance` wins. |
| `RETENTION_AUTHORIZATION_DECISION_LOGS_DAYS` | unset (keep) | Delete authorization decision logs older than N days (min 7). |
| `RETENTION_ACTIVITY_TIMELINE_EVENTS_DAYS` | unset (keep) | Delete activity timeline events older than N days (min 7). |
| `RETENTION_WEBHOOK_DELIVERIES_DAYS` | unset (keep) | Delete webhook deliveries older than N days (min 7). |
| `RETENTION_DELETE_BATCH_SIZE` | `5000` | Rows per delete batch (100 to 50000); each batch commits. |
| `RETENTION_MAX_BATCHES_PER_RUN` | `200` | Non-empty batches per table per run; the rest waits for the next run. |
| `RETENTION_ENABLED` | `true` | Kill switch: `false` stops all retention deletes and partition drops. |

`scripts/partition_table.py` (`plan`, `create-shadow`, `backfill --batch-size`, `swap`,
`verify`, and `--dry-run` on the subcommands that change data) converts a table to monthly
partitions. It is an operator tool that is never run automatically. Rehearse every
conversion on staging volume first.

## Prometheus & Grafana Observability

- Enable application metrics with `METRICS_ENABLED=true` in `.env`.
- Scrape endpoint is exposed at `GET /metrics` (and `GET /api/v1/metrics`).
- Optional bearer authentication: set `METRICS_REQUIRE_AUTH=true` and `METRICS_BEARER_TOKEN=<token>`.
- Celery worker metrics: set `WORKER_METRICS_ENABLED=true` to expose Celery task metrics on `WORKER_METRICS_PORT=9808`.
- Start Prometheus, Alertmanager, Grafana, and infrastructure exporters with `make up-observability` from repository root.
- Browser Web Vitals (R07-11): set `WEB_VITALS_INGEST_ENABLED=true` to accept `POST /api/v1/telemetry/web-vitals` (404 otherwise). Samples go to `rudix_web_vitals_value_ms`, `rudix_web_vitals_cls` and `rudix_web_vitals_samples_total` only (nothing stored or logged); `WEB_VITALS_MAX_ROUTES` (200) bounds the `route` label and `WEB_VITALS_RATE_LIMIT_PER_MINUTE` (60) limits each client IP. Dashboard: `infra/observability/grafana/dashboards/web-vitals.json`.

## Directory overview

```text
backend/
  app/
    api/
    clients/
    core/
    db/
    models/
    schemas/
    services/
    workers/
    repositories/
  alembic/
  scripts/
  tests/
```
