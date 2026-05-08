# Backend Scaffold (FastAPI)

This folder contains a production-ready backend skeleton for the AI Document Q&A Assistant.

## Includes

- FastAPI app structure with versioned API routers.
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
- `clerk` and `supabase` auth providers are scaffold placeholders and are not implemented yet.
- Dependency clients are initialized through centralized factories (`app/clients/factory.py`) for consistent timeout/retry handling.
- Startup bootstraps MinIO bucket and Qdrant collection idempotently when enabled (`MINIO_BOOTSTRAP_BUCKET`, `QDRANT_BOOTSTRAP_COLLECTION`).
- Qdrant collection bootstrap validates vector schema (`QDRANT_VECTOR_SIZE`, `QDRANT_DISTANCE`) and fails fast on mismatch.
- Celery uses explicit queues/routes for document processing, deletion, re-indexing, and evaluations.
- Celery tasks use a shared retry policy (`CELERY_TASK_MAX_RETRIES`, backoff, jitter) and structured failure logging.
- Task terminal failures mark related document/evaluation rows as `failed` where applicable.
- Redis-backed endpoint rate limiting is configurable and disabled by default in development/test (`RATE_LIMIT_DISABLE_IN_DEVELOPMENT`, `RATE_LIMIT_DISABLE_IN_TEST`).
- Chunking/index metadata is environment-driven (`CHUNK_SIZE_TOKENS`, `CHUNK_OVERLAP_TOKENS`, `DOCUMENT_INDEX_VERSION`).
- Production profile requires `SENTRY_DSN`.
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
- `documents/{document_id}`, `chat` `document_ids`, and `evaluations.document_id` are org-scoped; cross-org lookups return `404`.
- Retrieval-side qdrant filters must include `organization_id` (see `app/services/qdrant_filters.py`).

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
