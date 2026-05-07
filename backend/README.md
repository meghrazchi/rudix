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
- URL-like settings are strictly validated (database, Qdrant, MinIO, RabbitMQ, Redis, auth JWKS, and service base URLs).
- Dependency clients are initialized through centralized factories (`app/clients/factory.py`) for consistent timeout/retry handling.
- Startup bootstraps MinIO bucket and Qdrant collection idempotently when enabled (`MINIO_BOOTSTRAP_BUCKET`, `QDRANT_BOOTSTRAP_COLLECTION`).
- Qdrant collection bootstrap validates vector schema (`QDRANT_VECTOR_SIZE`, `QDRANT_DISTANCE`) and fails fast on mismatch.
- Production profile requires `SENTRY_DSN`.
- Structured logging is configured for both API and Celery worker.
- `LOG_FORMAT=auto` emits readable console logs in development and JSON logs in staging/production.

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
