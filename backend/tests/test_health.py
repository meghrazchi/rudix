import os

import pytest
from fastapi.testclient import TestClient

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
os.environ.setdefault("CLERK_JWT_ISSUER", "https://clerk.example.com")
os.environ.setdefault("CLERK_JWT_AUDIENCE", "rudix-api")

from app.main import app
from app.shared.schemas.common import HealthDependency


def _ok_dependency() -> HealthDependency:
    return HealthDependency(ok=True)


def _patch_ready_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok_async() -> bool:
        return True

    monkeypatch.setattr("app.api.health.check_database_health", _ok_async)
    monkeypatch.setattr("app.api.health.check_redis_health", _ok_async)
    monkeypatch.setattr("app.api.health.check_rabbitmq_health", _ok_async)
    monkeypatch.setattr("app.api.health.check_qdrant_health", lambda: True)
    monkeypatch.setattr("app.api.health.check_minio_health", lambda: True)
    monkeypatch.setattr("app.api.health._openai_configuration_health", _ok_dependency)


def test_health_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["failed_dependencies"] == []


def test_healthz_alias_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_ready_returns_ok_when_all_dependencies_are_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ready_all_ok(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["failed_dependencies"] == []
    assert payload["dependencies"]["postgres"]["ok"] is True
    assert payload["dependencies"]["redis"]["ok"] is True
    assert payload["dependencies"]["rabbitmq"]["ok"] is True
    assert payload["dependencies"]["qdrant"]["ok"] is True
    assert payload["dependencies"]["minio"]["ok"] is True
    assert payload["dependencies"]["openai_config"]["ok"] is True


@pytest.mark.parametrize(
    ("dependency_name", "patch_target", "patch_value"),
    [
        ("postgres", "app.api.health.check_database_health", False),
        ("redis", "app.api.health.check_redis_health", False),
        ("rabbitmq", "app.api.health.check_rabbitmq_health", False),
        ("qdrant", "app.api.health.check_qdrant_health", False),
        ("minio", "app.api.health.check_minio_health", False),
        ("openai_config", "app.api.health._openai_configuration_health", HealthDependency(ok=False, detail="openai_api_key_missing")),
    ],
)
def test_ready_returns_503_with_failed_dependency_list(
    monkeypatch: pytest.MonkeyPatch,
    dependency_name: str,
    patch_target: str,
    patch_value: bool | HealthDependency,
) -> None:
    _patch_ready_all_ok(monkeypatch)

    if "openai_configuration_health" in patch_target:
        monkeypatch.setattr(patch_target, lambda: patch_value)
    elif "check_qdrant_health" in patch_target or "check_minio_health" in patch_target:
        monkeypatch.setattr(patch_target, lambda: patch_value)
    else:
        async def _failing_async() -> bool:
            return bool(patch_value)

        monkeypatch.setattr(patch_target, _failing_async)

    client = TestClient(app)
    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert dependency_name in payload["failed_dependencies"]
    assert payload["dependencies"][dependency_name]["ok"] is False


def test_ready_metadata_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ready_all_ok(monkeypatch)
    client = TestClient(app)

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    payload = response.json()
    serialized = str(payload)

    assert "postgres:postgres@" not in serialized
    assert "guest:guest@" not in serialized


def test_ready_returns_503_when_dependency_checker_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ready_all_ok(monkeypatch)

    def _raise_minio() -> bool:
        raise RuntimeError("minio check crashed")

    monkeypatch.setattr("app.api.health.check_minio_health", _raise_minio)

    client = TestClient(app)
    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert "minio" in payload["failed_dependencies"]
    assert payload["dependencies"]["minio"]["ok"] is False


def test_configz_hides_secret_values() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/configz")

    assert response.status_code == 200
    payload = response.json()

    assert payload["openai_api_key_set"] is True
    assert payload["minio_secret_key_set"] is True
    assert "sk-test" not in str(payload)
