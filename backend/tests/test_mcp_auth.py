import os

import pytest

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
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.errors import AuthenticationError
from app.core.config import MCPTransport, settings
from app.mcp.auth import resolve_mcp_principal


async def test_stdio_transport_uses_configured_dev_principal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mcp_transport", MCPTransport.stdio)
    monkeypatch.setattr(settings, "mcp_dev_principal_user_id", "user-dev-001")
    monkeypatch.setattr(settings, "mcp_dev_principal_organization_id", "org-dev-001")
    monkeypatch.setattr(settings, "mcp_dev_principal_roles", ["owner", "admin"])

    principal = await resolve_mcp_principal(headers={})

    assert principal.user_id == "user-dev-001"
    assert principal.organization_id == "org-dev-001"
    assert principal.roles == ["owner", "admin"]
    assert principal.auth_provider == "mcp_dev"


async def test_streamable_http_missing_bearer_token_fails_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mcp_transport", MCPTransport.streamable_http)
    monkeypatch.setattr(settings, "mcp_require_bearer_auth", True)

    with pytest.raises(AuthenticationError, match="Missing bearer token"):
        await resolve_mcp_principal(headers={})


async def test_streamable_http_can_fallback_to_dev_principal_when_auth_is_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mcp_transport", MCPTransport.streamable_http)
    monkeypatch.setattr(settings, "mcp_require_bearer_auth", False)
    monkeypatch.setattr(settings, "mcp_dev_principal_user_id", "user-dev-optional")
    monkeypatch.setattr(settings, "mcp_dev_principal_organization_id", "org-dev-optional")
    monkeypatch.setattr(settings, "mcp_dev_principal_roles", ["viewer"])

    principal = await resolve_mcp_principal(headers={})

    assert principal.user_id == "user-dev-optional"
    assert principal.organization_id == "org-dev-optional"
    assert principal.roles == ["viewer"]

