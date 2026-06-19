from __future__ import annotations

import os
from uuid import uuid4

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
from app.domains.quota.repositories.quota_repository import QuotaRepository
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def billing_client(
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
    get_auth_provider.cache_clear()


async def _seed_org_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
) -> tuple[Organization, User]:
    organization = Organization(
        name=f"Billing {uuid4().hex[:8]}",
        slug=f"billing-{uuid4().hex[:8]}",
    )
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"billing-user-{uuid4().hex[:8]}",
        email=f"billing-{uuid4().hex[:8]}@example.com",
        display_name="Billing User",
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
    return organization, user


async def _seed_managed_billing_state(
    db_session: AsyncSession,
    *,
    organization: Organization,
    user: User,
) -> None:
    repo = QuotaRepository()
    await repo.upsert_policy(
        db_session,
        organization_id=organization.id,
        limits={
            "seats": {"soft_limit": 4, "hard_limit": 5, "reset_window": "none"},
            "uploads": {"soft_limit": 120, "hard_limit": 150, "reset_window": "per_month"},
            "questions": {"soft_limit": 1000, "hard_limit": 1200, "reset_window": "per_month"},
            "tokens": {
                "soft_limit": 2_000_000,
                "hard_limit": 2_500_000,
                "reset_window": "per_month",
            },
            "storage_bytes": {
                "soft_limit": 5_000_000_000,
                "hard_limit": 7_500_000_000,
                "reset_window": "none",
            },
            "evaluations": {"soft_limit": 10, "hard_limit": 20, "reset_window": "per_day"},
            "agent_runs": {"soft_limit": 5, "hard_limit": 10, "reset_window": "per_day"},
            "connectors": {"soft_limit": 3, "hard_limit": 5, "reset_window": "none"},
        },
        updated_by_id=user.id,
    )
    await repo.upsert_usage(
        db_session,
        organization_id=organization.id,
        quota_type="uploads",
        current_value=42,
    )
    await repo.upsert_usage(
        db_session,
        organization_id=organization.id,
        quota_type="questions",
        current_value=315,
    )
    await repo.upsert_usage(
        db_session,
        organization_id=organization.id,
        quota_type="tokens",
        current_value=1_200_000,
    )
    await repo.upsert_usage(
        db_session,
        organization_id=organization.id,
        quota_type="storage_bytes",
        current_value=2_147_483_648,
    )
    await repo.upsert_usage(
        db_session,
        organization_id=organization.id,
        quota_type="evaluations",
        current_value=4,
    )
    await repo.upsert_usage(
        db_session,
        organization_id=organization.id,
        quota_type="agent_runs",
        current_value=2,
    )
    await repo.upsert_usage(
        db_session,
        organization_id=organization.id,
        quota_type="connectors",
        current_value=1,
    )
    await db_session.commit()


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_billing_plan_and_quotas_for_billing_admin(
    billing_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization, user = await _seed_org_user(db_session, role=OrganizationRole.billing_admin)
    await _seed_managed_billing_state(db_session, organization=organization, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    plan_response = await billing_client.get(
        "/api/v1/billing/plan",
        headers=_auth_headers(token),
    )
    assert plan_response.status_code == 200
    plan = plan_response.json()
    assert plan["plan_name"] == "Managed plan"
    assert plan["status"] == "active"
    assert plan["seats_used"] == 1
    assert plan["can_manage_subscription"] is True

    quotas_response = await billing_client.get(
        "/api/v1/billing/quotas",
        headers=_auth_headers(token),
    )
    assert quotas_response.status_code == 200
    quotas = quotas_response.json()
    assert any(quota["resource"] == "uploads" for quota in quotas)
    assert any(quota["resource"] == "storage_bytes" for quota in quotas)
    assert any(quota["resource"] == "questions" for quota in quotas)

    invoices_response = await billing_client.get(
        "/api/v1/billing/invoices",
        headers=_auth_headers(token),
    )
    assert invoices_response.status_code == 200
    invoices = invoices_response.json()
    assert len(invoices) >= 1
    assert invoices[0]["download_url"] is None


@pytest.mark.asyncio
async def test_billing_contact_redacts_raw_payment_data(
    billing_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization, user = await _seed_org_user(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await billing_client.get(
        "/api/v1/billing/contact",
        headers=_auth_headers(token),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["payment_method_summary"] == "Managed securely in the billing portal"
    assert "4242424242424242" not in response.text
    assert "card_number" not in payload

    update_response = await billing_client.patch(
        "/api/v1/billing/contact",
        headers=_auth_headers(token),
        json={
            "email": "billing@example.com",
            "payment_method_summary": "Visa ending 4242",
        },
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["payment_method_summary"] == "Managed securely in the billing portal"
    assert updated["email"] == "billing@example.com"


@pytest.mark.asyncio
async def test_billing_endpoints_require_billing_permission(
    billing_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    organization, user = await _seed_org_user(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await billing_client.get(
        "/api/v1/billing/plan",
        headers=_auth_headers(token),
    )
    assert response.status_code == 403

    portal_response = await billing_client.post(
        "/api/v1/billing/portal-session",
        headers=_auth_headers(token),
    )
    assert portal_response.status_code == 403
