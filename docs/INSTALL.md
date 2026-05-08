# Installation and Configuration

This guide covers development and production installation for the current stack:

- FastAPI API + Celery worker
- PostgreSQL, Qdrant, MinIO, RabbitMQ, Redis
- Docker Compose as the default runtime

## 1. Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Git
- OpenAI API key
- App auth secret (`APP_AUTH_SECRET`) for the default app-managed provider

Optional for local non-container backend runtime:

- Python 3.12
- `make`

## 2. Clone and bootstrap

```bash
git clone <your-repo-url>
cd rudix
cp .env.example .env
```

Update `.env` before first start:

- `OPENAI_API_KEY`
- `AUTH_PROVIDER` (default: `app`)
- `APP_AUTH_SECRET` when `AUTH_PROVIDER=app`
- `APP_AUTH_ACCESS_TOKEN_TTL_SECONDS`, `APP_AUTH_ISSUER`, `APP_AUTH_AUDIENCE` (optional overrides)
- Provider JWKS URL (future providers):
  - `CLERK_JWKS_URL` when `AUTH_PROVIDER=clerk`
  - `SUPABASE_JWKS_URL` when `AUTH_PROVIDER=supabase`
- `LOG_FORMAT`:
  - `auto` (default): console in development/test, JSON in staging/production
  - `json`: force JSON logs
  - `console`: force developer-readable console logs
- Rate-limit settings (optional):
  - `RATE_LIMIT_ENABLED`
  - `RATE_LIMIT_DISABLE_IN_DEVELOPMENT`
  - `RATE_LIMIT_DISABLE_IN_TEST`
  - `RATE_LIMIT_REDIS_FAILURE_MODE` (`open` or `closed`)
  - endpoint-specific limits (`RATE_LIMIT_*_REQUESTS`)

`Settings` loads `.env` from either:

- `backend/.env`
- repository root `.env`

Connection URL strategy in this repo:

- `.env` uses `localhost` endpoints so host-run API/worker works out of the box.
- `docker-compose.yml` overrides API/worker connection URLs to Docker service hostnames (`postgres`, `redis`, `rabbitmq`, `minio`, `qdrant`).

## 3. Development installation

### 3.1 Start full stack (recommended)

```bash
docker compose up --build
```

Equivalent via repo root Makefile:

```bash
make up
```

Run detached:

```bash
make up-d
```

Services:

- API: `http://localhost:8000`
- MinIO API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`
- RabbitMQ UI: `http://localhost:15672`
- Qdrant: `http://localhost:6333`

### 3.2 Validate startup

```bash
curl -fsS http://localhost:8000/api/v1/health
curl -fsS http://localhost:8000/api/v1/ready
curl -fsS http://localhost:8000/api/v1/configz
```

Notes:

- Startup is fail-fast. API and worker stop immediately on invalid or missing required configuration.
- `/api/v1/configz` returns a sanitized snapshot and never exposes secret values.
- Docker waits for healthchecks on API dependencies: PostgreSQL, Qdrant, MinIO, RabbitMQ, and Redis.

### 3.3 Run database migrations and seed data

From `backend/`:

```bash
make migrate
make seed-dev
```

Rollback the most recent migration in local development:

```bash
make downgrade
```

### 3.4 Optional: run backend outside Docker

Keep infrastructure containers up, but run API/worker from host:

```bash
docker compose up -d postgres qdrant minio minio-init rabbitmq redis
cd backend
make install
make run-api
```

In another terminal:

```bash
cd backend
make run-worker
```

Notes:

- `make install` creates `backend/.venv` and installs dependencies there.
- This avoids Homebrew macOS `externally-managed-environment` errors (PEP 668).
- You do not need to activate the virtualenv for `make run-api`, `make run-worker`, `make test`, or `make lint`.

### 3.5 Stack lifecycle commands (repo root)

```bash
make up
make up-d
make down
make down-v
make ps
make logs
make logs-api
make logs-worker
make logs-infra
make migrate
make test
```

### 3.6 Useful Celery and task commands

Common worker/task operations from `backend/`:

```bash
# Start API and worker locally (infra still in Docker)
make run-api
make run-worker

# Check workers and queues
.venv/bin/celery -A app.workers.celery_app:celery_app status
.venv/bin/celery -A app.workers.celery_app:celery_app inspect active_queues

# Inspect tasks
.venv/bin/celery -A app.workers.celery_app:celery_app inspect registered
.venv/bin/celery -A app.workers.celery_app:celery_app inspect active
.venv/bin/celery -A app.workers.celery_app:celery_app inspect reserved
.venv/bin/celery -A app.workers.celery_app:celery_app inspect scheduled

# Purge queued tasks (destructive for queued messages)
.venv/bin/celery -A app.workers.celery_app:celery_app purge -f
```

Dispatch a document processing task with a real UUID:

```bash
# From repo root, fetch a real document UUID
DOC_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from documents order by created_at desc limit 1;")

# From backend/, enqueue task
DOC_ID="$DOC_ID" .venv/bin/python -c "import os; from app.workers.document_tasks import process_document; doc=os.environ['DOC_ID'].strip(); r=process_document.delay(doc, force=True); print('doc_id=', doc); print('task_id=', r.id)"
```

Important:

- Do not send placeholder IDs like `PUT_DOC_UUID_HERE` or `<DOC_UUID>`.
- `force=true` bypasses idempotency skip checks, but does not bypass UUID validation.
- If you run both local and Docker workers, tasks can be consumed by either worker.

Docker-specific worker operations from repo root:

```bash
docker compose logs -f worker
docker compose exec -T worker celery -A app.workers.celery_app:celery_app inspect active
docker compose exec -T worker celery -A app.workers.celery_app:celery_app inspect reserved
docker compose exec -T worker celery -A app.workers.celery_app:celery_app inspect scheduled
```

## 4. Production installation

### 4.1 Environment profile

Set:

```env
ENVIRONMENT=production
```

In production, `SENTRY_DSN` is required by config validation.

Valid values:

- `development`
- `test`
- `staging`
- `production`

### 4.2 Required production configuration

At minimum, set these values to production endpoints/secrets:

```env
ENVIRONMENT=production
LOG_LEVEL=INFO
LOG_FORMAT=json

API_BASE_URL=https://api.yourdomain.com
FRONTEND_BASE_URL=https://app.yourdomain.com
CORS_ORIGINS=https://app.yourdomain.com

DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>
QDRANT_URL=https://<qdrant-host>
QDRANT_API_KEY=<qdrant-api-key>
QDRANT_COLLECTION=documents
QDRANT_VECTOR_SIZE=1536
QDRANT_DISTANCE=cosine
QDRANT_TIMEOUT_SECONDS=2
QDRANT_BOOTSTRAP_COLLECTION=true

MINIO_ENDPOINT=https://<minio-or-s3-endpoint>
MINIO_ACCESS_KEY=<access-key>
MINIO_SECRET_KEY=<secret-key>
MINIO_BUCKET=documents
MINIO_BOOTSTRAP_BUCKET=true

RABBITMQ_URL=amqps://<user>:<password>@<host>/<vhost>
RABBITMQ_CONNECT_TIMEOUT_SECONDS=2
CELERY_RESULT_BACKEND_ENABLED=true
CELERY_TASK_DEFAULT_QUEUE=default
CELERY_QUEUE_DOCUMENTS_PROCESSING=documents.processing
CELERY_QUEUE_DOCUMENTS_DELETION=documents.deletion
CELERY_QUEUE_DOCUMENTS_REINDEX=documents.reindex
CELERY_QUEUE_EVALUATIONS=evaluations
CELERY_TASK_MAX_RETRIES=5
CELERY_RETRY_BACKOFF_SECONDS=2
CELERY_RETRY_BACKOFF_MAX_SECONDS=60
CELERY_RETRY_JITTER=true
CELERY_WORKER_PREFETCH_MULTIPLIER=1
REDIS_URL=redis://:<password>@<host>:6379/0
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS=2
REDIS_SOCKET_TIMEOUT_SECONDS=2

DEPENDENCY_CONNECT_TIMEOUT_SECONDS=1
DEPENDENCY_READ_TIMEOUT_SECONDS=1
DEPENDENCY_MAX_RETRIES=0

OPENAI_API_KEY=<openai-api-key>
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_LLM_MODEL=gpt-5.4-mini

AUTH_PROVIDER=app
APP_AUTH_SECRET=<strong-random-secret>
APP_AUTH_ACCESS_TOKEN_TTL_SECONDS=3600
APP_AUTH_ISSUER=rudix-app
APP_AUTH_AUDIENCE=rudix-api
# Future external providers (currently scaffold placeholders):
# AUTH_PROVIDER=clerk
# CLERK_JWKS_URL=https://<clerk-domain>/.well-known/jwks.json
# AUTH_PROVIDER=supabase
# SUPABASE_JWKS_URL=https://<project>.supabase.co/auth/v1/keys

SENTRY_DSN=https://<key>@<sentry-host>/<project-id>

FEATURE_EXPOSE_CONFIG_SNAPSHOT=false
```

### 4.3 Run production stack

```bash
docker compose up -d --build
```

Then verify health:

```bash
curl -fsS https://api.yourdomain.com/api/v1/health
curl -fsS https://api.yourdomain.com/api/v1/ready
```

Apply schema migrations before serving traffic:

```bash
cd backend
make migrate
```

## 5. Configuration validation behavior

The settings layer validates on startup:

- Required URLs/DSNs are syntactically valid.
- Numeric limits are within safe bounds.
- Cross-field constraints are enforced:
  - `RETRIEVAL_FINAL_TOP_K <= RETRIEVAL_INITIAL_TOP_K`
  - `CHUNK_OVERLAP_TOKENS < CHUNK_SIZE_TOKENS`
- `APP_AUTH_SECRET` is required for `AUTH_PROVIDER=app`.
- `CLERK_JWKS_URL` is required for `AUTH_PROVIDER=clerk`.
- `SUPABASE_JWKS_URL` is required for `AUTH_PROVIDER=supabase`.
- In production with `AUTH_PROVIDER=app`, `APP_AUTH_SECRET` must not be `dev-insecure-change-me`.
- OpenAI API key is required when related features are enabled.
- `SENTRY_DSN` is required in production profile.

Any validation error stops startup with a clear message.

Dependency initialization behavior:

- Redis initializes with configured socket timeouts and an initial ping check.
- RabbitMQ broker URL is parsed/validated during startup and readiness checks.
- MinIO client uses shared retry/timeout settings and can auto-create bucket idempotently.
- Qdrant client uses shared timeout settings and can auto-create collection idempotently.
- Celery queues/routes are explicit for `documents.process`, `documents.delete`, `documents.reindex`, and `evaluations.run`.
- Celery retries transient task failures with backoff/jitter and logs terminal failures with task/job identifiers.
- Redis-backed endpoint rate limiting returns `429` with `Retry-After` metadata when enabled and limits are exceeded.
- Redis limiter failures are either degraded-open or fail-closed based on `RATE_LIMIT_REDIS_FAILURE_MODE`.

## 6. Protected API authentication (app-managed)

The currently implemented auth provider is app-managed (`AUTH_PROVIDER=app`).

- Protected routes use one dependency (`get_current_principal`).
- Auth provider is selected via `AUTH_PROVIDER`.
- Authorization is enforced from PostgreSQL user/organization membership data.
- `clerk` and `supabase` providers are scaffold placeholders and will return `401` until implemented.

Generate a local app token for testing:

```bash
cd backend
.venv/bin/python - <<'PY'
from app.auth.token_codec import create_app_access_token
token = create_app_access_token(
    subject="seed-user-001",  # matches seed_dev.py external_auth_id
    expires_in_seconds=3600,
)
print(token)
PY
```

Call a protected endpoint:

```bash
TOKEN="<paste_token>"
ORG_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from organizations where slug='demo-org' limit 1;")
curl -i http://localhost:8000/api/v1/pipeline/steps \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: ${ORG_ID:-<org_uuid>}"
```

Common auth responses:

- `401`: missing/invalid/expired token.
- `403`: authenticated, but cross-organization access or insufficient role.

Current role checks:

- `pipeline/*`: any authenticated org member role (`owner|admin|member|viewer`)
- `documents/upload` and `documents/upload-url`: `owner|admin|member`
- `evaluations` (POST): `owner|admin`
- `documents/{document_id}`, `chat` `document_ids`, and `evaluations.document_id` are org-scoped; cross-org lookups return `404`.

Retrieval note:

- Qdrant filter construction must always include `organization_id` (guard helper: `app/services/qdrant_filters.py`).

Useful verification commands:

```bash
cd backend

# Targeted authorization regression tests
.venv/bin/pytest tests/test_auth_provider.py tests/test_auth_api.py tests/test_qdrant_filters.py -q

# Rate-limit tests (unit + API)
.venv/bin/pytest tests/test_rate_limit.py -q

# Generate app token from seeded user
TOKEN=$(.venv/bin/python - <<'PY'
from app.auth.token_codec import create_app_access_token
print(create_app_access_token(subject="seed-user-001", expires_in_seconds=3600))
PY
)

# Get seeded org id (after `make seed-dev`)
ORG_ID=$(docker compose exec -T postgres psql -U postgres -d rag_app -At -c "select id from organizations where slug='demo-org' limit 1;")  

# Valid authenticated request
curl -i http://localhost:8000/api/v1/pipeline/steps \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID"

# Valid document upload (PDF/TXT/DOCX only)
curl -i http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID" \
  -F "file=@/absolute/path/to/sample.pdf;type=application/pdf"

# Upload response should include: "status":"uploaded","queue_status":"queued"

# Confirm uploaded object is present in MinIO
docker compose run --rm minio-init /bin/sh -lc \
  'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null && mc ls --recursive "local/$MINIO_BUCKET"'

# Confirm lifecycle row exists in PostgreSQL
docker compose exec -T postgres psql -U postgres -d rag_app -c \
  "select id, organization_id, uploaded_by_user_id, status, file_type, storage_bucket, storage_object_key, checksum from documents order by created_at desc limit 5;"

# Confirm worker consumed process task
docker compose logs --tail=100 worker | rg "document.processing.(started|completed|failed|skipped)"

# Document-safe not-found behavior for inaccessible/non-existent ids
curl -i http://localhost:8000/api/v1/documents/11111111-1111-1111-1111-111111111111 \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-ID: $ORG_ID"
```

Upload behavior note:

- Duplicate file uploads are accepted and stored as separate documents. Each upload gets a new `document_id` and a new MinIO object key.
- Each successful upload enqueues `documents.process`; if publish fails, API returns `503` and leaves the document in `uploaded` for retry/recovery.

## 7. Security recommendations

- Do not commit `.env`.
- Store secrets in a secret manager in production.
- Keep `FEATURE_EXPOSE_CONFIG_SNAPSHOT=false` in production.
- Use TLS for all public and service endpoints.
