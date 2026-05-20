# Backend Scaffold (FastAPI)

This folder contains a production-ready backend skeleton for the AI Document Q&A Assistant.

## Includes

- FastAPI app structure with versioned API routers.
- Domain-driven backend structure under `app/domains/*` (admin, auth, chat, documents, evaluations, pipeline).
- Strict environment-based configuration and fail-fast validation.
- SQLAlchemy async database foundation and Alembic scaffold.
- Celery worker scaffold with RabbitMQ/Redis wiring.
- Client scaffolds for Qdrant and MinIO.
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

3. API health endpoints:

- `GET http://localhost:8000/api/v1/health`
- `GET http://localhost:8000/api/v1/ready`
- `GET http://localhost:8000/api/v1/configz` (sanitized settings snapshot, controlled by `FEATURE_EXPOSE_CONFIG_SNAPSHOT`)

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
- `clerk` auth provider is implemented with JWKS-based JWT verification (signature, issuer, audience, expiry, subject).
- `supabase` provider wiring exists and uses the same JWKS verifier contract, but requires provider-specific JWT settings and full integration validation.
- Dependency clients are initialized through centralized factories (`app/clients/factory.py`) for consistent timeout/retry handling.
- Startup bootstraps MinIO bucket and Qdrant collection idempotently when enabled (`MINIO_BOOTSTRAP_BUCKET`, `QDRANT_BOOTSTRAP_COLLECTION`).
- Qdrant collection bootstrap validates vector schema (`QDRANT_VECTOR_SIZE`, `QDRANT_DISTANCE`) and fails fast on mismatch.
- Celery uses explicit queues/routes for document processing, deletion, re-indexing, and evaluations.
- Celery tasks use a shared retry policy (`CELERY_TASK_MAX_RETRIES`, backoff, jitter) and structured failure logging.
- Task terminal failures mark related document/evaluation rows as `failed` where applicable.
- Redis-backed endpoint rate limiting is configurable and disabled by default in development/test (`RATE_LIMIT_DISABLE_IN_DEVELOPMENT`, `RATE_LIMIT_DISABLE_IN_TEST`).
- Chunking/index metadata is environment-driven (`CHUNK_SIZE_TOKENS`, `CHUNK_OVERLAP_TOKENS`, `DOCUMENT_INDEX_VERSION`).
- Production profile requires `SENTRY_DSN`.
- Sentry runtime settings are environment-driven (`SENTRY_*`), including optional per-env sampling controls.
- Non-production test event endpoint is available at `POST /api/v1/sentry-test` when enabled.
- Structured logging is configured for both API and Celery worker.
- `LOG_FORMAT=auto` emits readable console logs in development and JSON logs in staging/production.

## Authentication quick check

Generate a local app token:

```bash
cd backend
.venv/bin/python - <<'PY'
from app.auth.token_codec import create_app_access_token
print(create_app_access_token(subject="seed-user-001", expires_in_seconds=3600))
PY
```

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
- `documents/upload` and `documents/upload-url`: `owner|admin|member`
- `evaluations` (POST): `owner|admin`
- `admin/usage` and `admin/audit-logs`: `owner|admin`
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
- Agent trace persistence uses `agent_runs`, `agent_steps`, `agent_tool_calls`, and `agent_approvals`.
- Side-effect tools require idempotency keys and should remain API-only unless explicitly approved for another surface.
- API and MCP adapters must share the same policy checks: role authorization, organization isolation, budgets, and safe output redaction.

## Development commands

```bash
make install
make lint
make test
make run-api
make run-worker
make migrate
make downgrade
make seed-dev
```

`make install` creates a local virtualenv at `backend/.venv` and installs all dependencies there.

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

Auth/authorization guard checks:

```bash
# Run targeted auth + qdrant filter tests
.venv/bin/pytest tests/test_auth_provider.py tests/test_auth_api.py tests/test_qdrant_filters.py -q

# Run rate-limit tests (unit + API behavior)
.venv/bin/pytest tests/test_rate_limit.py -q

# Build an app token for manual API checks
TOKEN=$(.venv/bin/python - <<'PY'
from app.auth.token_codec import create_app_access_token
print(create_app_access_token(subject="seed-user-001", expires_in_seconds=3600))
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
- Each successful upload immediately enqueues `documents.process`; if enqueue fails, API returns `503` and the document remains in `uploaded` state.
- Worker extraction currently supports PDF (page-by-page via PyMuPDF), TXT (UTF-8 with fallback), and DOCX (paragraphs + tables).
- Worker normalization removes null/control characters, normalizes whitespace/blank lines, and records `cleaning_*` stats in processing logs.
- Worker chunking stores `document_chunks` with deterministic `chunk_index`, `token_count`, `embedding_model`, and `index_version`; current-version chunks are replaced idempotently on reprocessing.
- Worker embedding generation batches chunk texts, retries transient provider failures with backoff, validates vector dimension, and records `document.embedding` usage events with token/cost metadata.
- Worker qdrant indexing upserts chunk vectors in batches with deterministic point IDs (`{document_id}:{index_version}:{chunk_index}`).
- Qdrant payloads include security and citation fields: `organization_id`, `user_id`, `document_id`, `chunk_id`, `filename`, `file_type`, `page_number`, `chunk_index`, `text`, `embedding_model`, `index_version`.
- Worker marks status transitions `uploaded -> processing -> indexed` and terminal failures as `failed`.
- Failure rows store a safe `error_message` plus structured `error_details` (stage/code/category/retryable/message) for frontend polling.

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
