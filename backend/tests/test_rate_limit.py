import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

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
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.factory import get_auth_provider
from app.auth.models import AuthenticatedPrincipal
from app.auth.token_codec import create_app_access_token
from app.clients import redis_client as redis_module
from app.core.config import AuthProvider, RateLimitRedisFailureMode, settings
from app.db.session import get_db_session
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.rate_limit import dependencies as rate_limit_dependencies
from app.rate_limit.dependencies import RateLimitScope


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expiries: dict[str, int] = {}
        self.expire_calls: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        count = self.counts.get(key, 0) + 1
        self.counts[key] = count
        return count

    async def expire(self, key: str, seconds: int) -> bool:
        self.expire_calls.append((key, seconds))
        self.expiries[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        return self.expiries.get(key, -1)


class BrokenRedis:
    async def incr(self, key: str) -> int:
        del key
        raise RuntimeError("redis unavailable")

    async def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        raise RuntimeError("redis unavailable")

    async def ttl(self, key: str) -> int:
        del key
        raise RuntimeError("redis unavailable")


@pytest_asyncio.fixture
async def rate_limit_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_disable_in_test", False)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_upload_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_chat_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_evaluation_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_admin_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.open)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_principal(db_session: AsyncSession, *, role: OrganizationRole) -> tuple[User, Organization]:
    organization = Organization(name="Rate Limit Org", slug=f"rl-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Rate Limit User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, organization


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


def _request_for(path: str, route_path: str) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "scheme": "http",
        "server": ("test", 80),
        "headers": [],
        "route": SimpleNamespace(path=route_path),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_rate_limit_consume_sets_expiry_for_new_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", fake_redis)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_disable_in_test", False)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_chat_requests", 5)
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.open)

    principal = AuthenticatedPrincipal(
        user_id="user-1",
        organization_id="org-1",
        roles=["member"],
        auth_provider="app",
    )

    await rate_limit_dependencies._consume(
        scope=RateLimitScope.chat,
        request=_request_for("/chat/sessions/s1/messages", "/chat/sessions/{session_id}/messages"),
        principal=principal,
    )

    assert len(fake_redis.expire_calls) == 1
    _, ttl_seconds = fake_redis.expire_calls[0]
    assert ttl_seconds == 60


@pytest.mark.asyncio
async def test_rate_limit_returns_429_when_limit_exceeded(
    rate_limit_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", FakeRedis())

    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    first_response = await rate_limit_client.post(
        "/api/v1/chat/sessions/session-1/messages",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"message": "hello", "document_ids": [], "stream": False},
    )
    second_response = await rate_limit_client.post(
        "/api/v1/chat/sessions/session-1/messages",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"message": "hello again", "document_ids": [], "stream": False},
    )

    assert first_response.status_code == 501
    assert second_response.status_code == 429
    assert second_response.headers["Retry-After"] == "60"
    payload = second_response.json()["detail"]
    assert payload["code"] == "rate_limit_exceeded"
    assert payload["retry_after_seconds"] == 60


@pytest.mark.asyncio
async def test_rate_limit_redis_failure_open_mode_degrades(
    rate_limit_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.open)

    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await rate_limit_client.post(
        "/api/v1/documents/upload-url",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "filename": "sample.pdf",
            "file_type": "pdf",
            "file_size_bytes": 1024,
        },
    )

    # Request reaches scaffold handler when limiter is degraded-open.
    assert response.status_code == 501


@pytest.mark.asyncio
async def test_rate_limit_redis_failure_closed_mode_blocks(
    rate_limit_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.closed)

    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await rate_limit_client.post(
        "/api/v1/documents/upload-url",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "filename": "sample.pdf",
            "file_type": "pdf",
            "file_size_bytes": 1024,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rate_limiter_unavailable"
