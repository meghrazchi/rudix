import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
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
from app.domains.admin.repositories.usage import UsageRepository
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import UsageEvent
from app.models.user import User


@pytest_asyncio.fixture
async def analytics_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_product_analytics", True)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_admin(
    db_session: AsyncSession,
    *,
    analytics_enabled: bool = True,
) -> tuple[User, Organization]:
    organization = Organization(
        name=f"Analytics Org {uuid4().hex[:8]}",
        slug=f"analytics-org-{uuid4().hex[:8]}",
        analytics_enabled=analytics_enabled,
    )
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"analytics-user-{uuid4().hex[:8]}",
        email=f"analytics-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db_session.commit()
    return user, organization


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
async def test_analytics_events_dedupe_activation_and_reject_sensitive_fields(
    analytics_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_admin(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    payload = {
        "event_name": "activation.first_upload",
        "schema_version": 1,
        "surface": "app",
        "route": "/documents",
        "page_key": "documents",
        "feature_area": "documents",
        "source": "upload",
    }
    first = await analytics_client.post(
        "/api/v1/analytics/events",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json=payload,
    )
    second = await analytics_client.post(
        "/api/v1/analytics/events",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json=payload,
    )
    rejected = await analytics_client.post(
        "/api/v1/analytics/events",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            **payload,
            "answer": "sensitive answer text",
        },
    )

    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert first.json()["deduped"] is False
    assert second.status_code == 200
    assert second.json()["deduped"] is True
    assert rejected.status_code == 422

    rows = await db_session.execute(
        select(UsageEvent).where(UsageEvent.organization_id == organization.id)
    )
    assert len(rows.scalars().all()) == 1


@pytest.mark.asyncio
async def test_analytics_summary_returns_zeroes_when_disabled(
    analytics_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_admin(db_session, analytics_enabled=False)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await analytics_client.get(
        "/api/v1/analytics/summary",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"from": "2026-05-01", "to": "2026-05-30"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is False
    assert payload["disabled_reason"] == "disabled_by_organization"
    assert payload["total_events"] == 0
    assert payload["activation"]["signup_completed"] == 0
    assert payload["feature_usage"] == {}


@pytest.mark.asyncio
async def test_analytics_summary_aggregates_activation_and_usage_events(
    analytics_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_admin(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    usage_repository = UsageRepository()
    upload_event = await usage_repository.create_usage_event(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        event_type="analytics.v1.activation.first_upload",
        input_tokens=None,
        output_tokens=None,
        cost_usd=Decimal("0"),
        metadata={
            "event_name": "activation.first_upload",
            "schema_version": 1,
            "surface": "app",
            "route": "/documents",
            "page_key": "documents",
            "feature_area": "documents",
            "source": "upload",
        },
    )
    upload_event.created_at = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    view_event = await usage_repository.create_usage_event(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        event_type="analytics.v1.feature.documents.viewed",
        input_tokens=None,
        output_tokens=None,
        cost_usd=Decimal("0"),
        metadata={
            "event_name": "feature.documents.viewed",
            "schema_version": 1,
            "surface": "app",
            "route": "/documents",
            "page_key": "documents",
            "feature_area": "documents",
        },
    )
    view_event.created_at = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)
    await db_session.commit()

    response = await analytics_client.get(
        "/api/v1/analytics/summary",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"from": "2026-05-01", "to": "2026-05-30"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["total_events"] == 2
    assert payload["activation"]["first_upload"] == 1
    assert payload["event_counts"]["activation.first_upload"] == 1
    assert payload["feature_usage"]["documents"] == 2
