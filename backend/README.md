# Backend Scaffold (FastAPI)

This folder contains a production-ready backend skeleton for the AI Document Q&A Assistant.

## Includes

- FastAPI app structure with versioned API routers.
- Strict environment-based configuration and validation.
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
```

3. API health endpoints:

- `GET http://localhost:8000/healthz`
- `GET http://localhost:8000/readyz`

## Development commands

```bash
make install
make lint
make test
make run-api
make run-worker
```

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
  alembic/
  tests/
```

