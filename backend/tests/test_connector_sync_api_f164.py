from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
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
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.quota.services.quota_service import upsert_policy_with_log
from app.interfaces.http import connector_sync as connector_sync_api
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def connector_sync_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(connector_sync_api, "ensure_connector_platform_enabled", lambda: None)

    class _FakePermissionReviewService:
        async def is_confirmed(self, *args: object, **kwargs: object) -> bool:
            del args, kwargs
            return True

    monkeypatch.setattr(
        connector_sync_api,
        "PermissionReviewService",
        lambda: _FakePermissionReviewService(),
    )
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_admin(
    db_session: AsyncSession,
) -> tuple[User, Organization]:
    org = Organization(name=f"Sync Org {uuid4().hex[:6]}", slug=f"sync-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"sync-user-{uuid4().hex[:8]}",
        email=f"sync-user-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db_session.commit()
    return user, org


async def _seed_quota_policy(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> None:
    await upsert_policy_with_log(
        db_session,
        organization_id=organization_id,
        limits={
            "connectors": {
                "soft_limit": 0,
                "hard_limit": 0,
                "reset_window": "none",
            }
        },
        updated_by_id=None,
        change_note="test quota policy",
    )
    await db_session.commit()


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/connectors/{connection_id}/sync/now",
        "/api/v1/connectors/{connection_id}/sync/full",
    ],
)
async def test_connector_sync_blocks_when_quota_is_exhausted(
    connector_sync_client: AsyncClient,
    db_session: AsyncSession,
    path: str,
) -> None:
    user, org = await _seed_admin(db_session)
    await _seed_quota_policy(db_session, organization_id=org.id)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    connection_id = uuid4()

    response = await connector_sync_client.post(
        path.format(connection_id=connection_id),
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 403
    payload = response.json()["detail"]
    assert payload["code"] == "plan_limit_exceeded"
    assert payload["quota_type"] == "connectors"
    assert payload["retryable"] is False
    assert payload["action"] == "Upgrade your plan or reduce connector sync usage."
