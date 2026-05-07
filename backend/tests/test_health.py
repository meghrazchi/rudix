import os

# Ensure strict settings can be loaded when app imports in tests.
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

from fastapi.testclient import TestClient

from app.main import app


def test_healthz_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_configz_hides_secret_values() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/configz")

    assert response.status_code == 200
    payload = response.json()

    assert payload["openai_api_key_set"] is True
    assert payload["minio_secret_key_set"] is True
    assert "sk-test" not in str(payload)
