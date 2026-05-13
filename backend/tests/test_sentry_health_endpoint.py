import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "clerk")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.com/.well-known/jwks.json")

from app.api import health


def _test_client() -> TestClient:
    app = FastAPI()
    app.include_router(health.router, prefix="/api/v1")
    return TestClient(app)


def test_sentry_test_endpoint_returns_404_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "settings", SimpleNamespace(is_sentry_test_event_enabled=False))
    client = _test_client()

    response = client.post("/api/v1/sentry-test")

    assert response.status_code == 404


def test_sentry_test_endpoint_returns_event_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "settings", SimpleNamespace(is_sentry_test_event_enabled=True))
    monkeypatch.setattr(health, "capture_sentry_test_event", lambda runtime="api": "evt_123")
    client = _test_client()

    response = client.post("/api/v1/sentry-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["event_id"] == "evt_123"


def test_sentry_test_endpoint_returns_503_when_sentry_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "settings", SimpleNamespace(is_sentry_test_event_enabled=True))
    monkeypatch.setattr(health, "capture_sentry_test_event", lambda runtime="api": None)
    client = _test_client()

    response = client.post("/api/v1/sentry-test")

    assert response.status_code == 503
