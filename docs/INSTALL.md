# Installation and Configuration

This guide covers development and production installation for the current stack:

- FastAPI API + Celery worker
- PostgreSQL, Qdrant, MinIO, RabbitMQ, Redis
- Docker Compose as the default runtime

## 1. Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Git
- OpenAI API key
- One auth provider setup:
  - Clerk JWKS URL, or
  - Supabase JWKS URL

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
- `AUTH_PROVIDER`
- Provider JWKS URL:
  - `CLERK_JWKS_URL` when `AUTH_PROVIDER=clerk`
  - `SUPABASE_JWKS_URL` when `AUTH_PROVIDER=supabase`
- `LOG_FORMAT`:
  - `auto` (default): console in development/test, JSON in staging/production
  - `json`: force JSON logs
  - `console`: force developer-readable console logs

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
REDIS_URL=redis://:<password>@<host>:6379/0
REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS=2
REDIS_SOCKET_TIMEOUT_SECONDS=2

DEPENDENCY_CONNECT_TIMEOUT_SECONDS=1
DEPENDENCY_READ_TIMEOUT_SECONDS=1
DEPENDENCY_MAX_RETRIES=0

OPENAI_API_KEY=<openai-api-key>
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
OPENAI_LLM_MODEL=gpt-5.4-mini

AUTH_PROVIDER=clerk
CLERK_JWKS_URL=https://<clerk-domain>/.well-known/jwks.json
# or:
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
- Auth-provider-specific JWKS URL is required.
- OpenAI API key is required when related features are enabled.
- `SENTRY_DSN` is required in production profile.

Any validation error stops startup with a clear message.

Dependency initialization behavior:

- Redis initializes with configured socket timeouts and an initial ping check.
- RabbitMQ broker URL is parsed/validated during startup and readiness checks.
- MinIO client uses shared retry/timeout settings and can auto-create bucket idempotently.
- Qdrant client uses shared timeout settings and can auto-create collection idempotently.

## 6. Security recommendations

- Do not commit `.env`.
- Store secrets in a secret manager in production.
- Keep `FEATURE_EXPOSE_CONFIG_SNAPSHOT=false` in production.
- Use TLS for all public and service endpoints.
