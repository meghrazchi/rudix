import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure strict settings can be loaded when importing modules in tests.
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
from app.main import app
from app.models.enums import OrganizationRole
from app.models.governance import OrganizationGovernancePolicy
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


@pytest_asyncio.fixture
async def governance_client(
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
) -> tuple[User, Organization]:
    organization = Organization(
        name=f"Governance Org {uuid4().hex[:6]}",
        slug=f"governance-org-{uuid4().hex[:8]}",
    )
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"governance-user-{uuid4().hex[:8]}",
        email=f"governance-{uuid4().hex[:8]}@example.com",
        display_name="Governance User",
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


@pytest.mark.asyncio
async def test_get_governance_policy_returns_defaults_for_admin(
    governance_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await governance_client.get(
        "/api/v1/admin/governance",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["organization_id"] == str(organization.id)
    assert payload["policy"]["allow_side_effect_tools"] is False
    assert len(payload["policy"]["allowed_tool_names"]) > 0
    assert len(payload["tool_catalog"]) > 0
    assert payload["mcp_status"]["mcp_http_path"].startswith("/")


@pytest.mark.asyncio
async def test_update_governance_policy_persists_and_audits(
    governance_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await governance_client.patch(
        "/api/v1/admin/governance",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "agentic_mode_enabled": True,
            "mcp_exposure_enabled": True,
            "allow_side_effect_tools": True,
            "allowed_tool_names": ["search_documents", "documents.delete"],
            "budgets": {
                "max_steps": 8,
                "max_tool_calls_per_run": 16,
                "max_tool_timeout_ms": 7000,
                "max_tool_input_bytes": 32768,
                "max_tool_output_bytes": 65536,
                "max_tool_retry_attempts": 1,
                "max_total_tokens": 12000,
                "max_total_cost_usd": 4.5,
            },
            "external_mcp_servers": [
                {
                    "server_id": "approved_server",
                    "enabled": True,
                    "transport": "streamable_http",
                    "base_url": "https://mcp.example.com/mcp",
                    "auth_type": "bearer",
                    "auth_secret_ref": "secret://mcp/prod/token",
                    "allow_tools": ["search_documents"],
                    "read_only_tools": ["search_documents"],
                    "side_effect_tools": [],
                    "required_roles": ["owner", "admin"],
                    "expose_on_mcp_surface": False,
                    "approval_required_for_side_effect": True,
                }
            ],
            "side_effect_warning_acknowledged": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["policy"]["agentic_mode_enabled"] is True
    assert payload["policy"]["allow_side_effect_tools"] is True
    assert "documents.delete" in payload["policy"]["allowed_tool_names"]
    assert payload["audit_recorded"] is True
    assert payload["changed_fields"]

    persisted = await db_session.scalar(
        select(OrganizationGovernancePolicy).where(
            OrganizationGovernancePolicy.organization_id == organization.id
        )
    )
    assert persisted is not None
    assert persisted.allow_side_effect_tools is True
    assert "documents.delete" in (persisted.allowed_tool_names_json or [])

    audit_logs = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.organization_id == organization.id,
                AuditLog.action == "admin.governance.policy.updated",
            )
        )
    ).scalars()
    assert list(audit_logs)


@pytest.mark.asyncio
async def test_update_governance_policy_requires_side_effect_ack(
    governance_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await governance_client.patch(
        "/api/v1/admin/governance",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "allow_side_effect_tools": True,
            "allowed_tool_names": ["documents.delete"],
        },
    )

    assert response.status_code == 422
    assert "side_effect_warning_acknowledged" in str(response.json()["detail"])


@pytest.mark.asyncio
async def test_governance_endpoint_requires_admin_role(
    governance_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await governance_client.get(
        "/api/v1/admin/governance",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role for requested operation"
