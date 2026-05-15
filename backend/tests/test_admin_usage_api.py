import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.repositories.usage import UsageRepository


@pytest_asyncio.fixture
async def admin_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_principal(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Admin Primary", slug=f"admin-primary-{uuid4().hex[:8]}")
    secondary_org = Organization(name="Admin Secondary", slug=f"admin-secondary-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, secondary_org])
    await db_session.flush()

    user = User(
        organization_id=primary_org.id,
        external_auth_id=f"admin-user-{uuid4().hex[:8]}",
        email=f"admin-{uuid4().hex[:8]}@example.com",
        display_name="Admin API User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=primary_org.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, primary_org, secondary_org


async def _seed_user_for_org(
    db_session: AsyncSession,
    *,
    organization: Organization,
    role: OrganizationRole = OrganizationRole.member,
) -> User:
    user = User(
        organization_id=organization.id,
        external_auth_id=f"admin-org-user-{uuid4().hex[:8]}",
        email=f"admin-org-{uuid4().hex[:8]}@example.com",
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
    return user


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
async def test_admin_usage_summary_aggregates_scoped_events(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, other_organization = await _seed_principal(
        db_session,
        role=OrganizationRole.admin,
    )
    other_user = await _seed_user_for_org(db_session, organization=other_organization, role=OrganizationRole.admin)

    usage_repository = UsageRepository()
    own_event_a = await usage_repository.create_usage_event(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        event_type="chat.query",
        model_name="gpt-5.4-mini",
        input_tokens=120,
        output_tokens=60,
        cost_usd=Decimal("0.0125"),
        metadata={"confidence_score": 0.8, "latency_ms": 300},
    )
    own_event_a.created_at = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)

    own_event_b = await usage_repository.create_usage_event(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        event_type="chat.query",
        model_name="gpt-5.4-mini",
        input_tokens=80,
        output_tokens=40,
        cost_usd=Decimal("0.0100"),
        metadata={"confidence_score": 0.6, "latency_ms": 500},
    )
    own_event_b.created_at = datetime(2026, 5, 2, 11, 30, tzinfo=UTC)

    _foreign_event = await usage_repository.create_usage_event(
        db_session,
        organization_id=other_organization.id,
        user_id=other_user.id,
        event_type="chat.query",
        model_name="gpt-5.4-mini",
        input_tokens=999,
        output_tokens=999,
        cost_usd=Decimal("1.999"),
        metadata={"confidence_score": 0.1, "latency_ms": 9999},
    )
    _foreign_event.created_at = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await admin_client.get(
        "/api/v1/admin/usage",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"from": "2026-05-01", "to": "2026-05-03", "granularity": "day"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["organization_id"] == str(organization.id)
    assert payload["range"] == {"from": "2026-05-01", "to": "2026-05-03"}
    assert payload["totals"]["event_count"] == 2
    assert payload["totals"]["input_tokens"] == 200
    assert payload["totals"]["output_tokens"] == 100
    assert payload["totals"]["cost_usd"] == pytest.approx(0.0225)
    assert payload["totals"]["avg_confidence"] == pytest.approx(0.7)
    assert payload["totals"]["avg_latency_ms"] == pytest.approx(400)
    assert len(payload["series"]) == 2
    assert payload["series"][0]["period_start"] == "2026-05-01"
    assert payload["series"][0]["event_count"] == 1
    assert payload["series"][1]["period_start"] == "2026-05-02"
    assert payload["series"][1]["event_count"] == 1


@pytest.mark.asyncio
async def test_admin_usage_endpoint_requires_admin_role(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await admin_client.get(
        "/api/v1/admin/usage",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role for requested operation"


@pytest.mark.asyncio
async def test_admin_audit_logs_list_scoped_with_filters(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, other_organization = await _seed_principal(
        db_session,
        role=OrganizationRole.owner,
    )
    other_user = await _seed_user_for_org(db_session, organization=other_organization, role=OrganizationRole.owner)
    usage_repository = UsageRepository()

    _own_audit = await usage_repository.create_audit_log(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        action="document.upload.accepted",
        resource_type="document",
        metadata={"request_id": "req-1", "status_code": 201},
    )
    _own_audit.created_at = datetime(2026, 5, 2, 10, 0, tzinfo=UTC)

    own_audit_second = await usage_repository.create_audit_log(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        action="chat.query.completed",
        resource_type="chat_session",
        metadata={"request_id": "req-2", "status_code": 200},
    )
    own_audit_second.created_at = datetime(2026, 5, 2, 10, 5, tzinfo=UTC)

    _foreign_audit = await usage_repository.create_audit_log(
        db_session,
        organization_id=other_organization.id,
        user_id=other_user.id,
        action="document.deleted",
        resource_type="document",
        metadata={"request_id": "req-foreign", "status_code": 200},
    )
    _foreign_audit.created_at = datetime(2026, 5, 2, 10, 10, tzinfo=UTC)
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await admin_client.get(
        "/api/v1/admin/audit-logs",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={
            "from": "2026-05-01",
            "to": "2026-05-03",
            "limit": 10,
            "offset": 0,
            "action": "chat.query.completed",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["organization_id"] == str(organization.id)
    assert item["action"] == "chat.query.completed"
    assert item["request_id"] == "req-2"
    assert item["metadata"]["status_code"] == 200


@pytest.mark.asyncio
async def test_admin_usage_rejects_invalid_date_range(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(
        db_session,
        role=OrganizationRole.admin,
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await admin_client.get(
        "/api/v1/admin/usage",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"from": "2026-05-10", "to": "2026-05-01"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "from must be less than or equal to to"
