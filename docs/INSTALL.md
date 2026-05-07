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

`Settings` loads `.env` from either:

- `backend/.env`
- repository root `.env`

## 3. Development installation

### 3.1 Start full stack (recommended)

```bash
docker compose up --build
```

Services:

- API: `http://localhost:8000`
- MinIO API: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`
- RabbitMQ UI: `http://localhost:15672`
- Qdrant: `http://localhost:6333`

### 3.2 Validate startup

```bash
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/readyz
curl -fsS http://localhost:8000/configz
```

Notes:

- Startup is fail-fast. API and worker stop immediately on invalid or missing required configuration.
- `/configz` returns a sanitized snapshot and never exposes secret values.

### 3.3 Optional: run backend outside Docker

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

If running API/worker from host, adjust connection URLs in `.env` to `localhost` endpoints.

Notes:

- `make install` creates `backend/.venv` and installs dependencies there.
- This avoids Homebrew macOS `externally-managed-environment` errors (PEP 668).
- You do not need to activate the virtualenv for `make run-api`, `make run-worker`, `make test`, or `make lint`.

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

API_BASE_URL=https://api.yourdomain.com
FRONTEND_BASE_URL=https://app.yourdomain.com
CORS_ORIGINS=https://app.yourdomain.com

DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>
QDRANT_URL=https://<qdrant-host>
QDRANT_API_KEY=<qdrant-api-key>

MINIO_ENDPOINT=https://<minio-or-s3-endpoint>
MINIO_ACCESS_KEY=<access-key>
MINIO_SECRET_KEY=<secret-key>
MINIO_BUCKET=documents

RABBITMQ_URL=amqps://<user>:<password>@<host>/<vhost>
REDIS_URL=redis://:<password>@<host>:6379/0

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
curl -fsS https://api.yourdomain.com/healthz
curl -fsS https://api.yourdomain.com/readyz
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

## 6. Security recommendations

- Do not commit `.env`.
- Store secrets in a secret manager in production.
- Keep `FEATURE_EXPOSE_CONFIG_SNAPSHOT=false` in production.
- Use TLS for all public and service endpoints.
