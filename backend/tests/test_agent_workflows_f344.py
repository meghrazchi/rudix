"""Tests for F344: plan-before-execute agent workflows."""

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
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def workflows_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_agents", True)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.viewer,
) -> tuple[User, Organization]:
    organization = Organization(
        name="Workflow Org",
        slug=f"workflow-org-{uuid4().hex[:8]}",
    )
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"workflow-user-{uuid4().hex[:8]}",
        email=f"workflow-{uuid4().hex[:8]}@example.com",
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
async def test_workflow_preview_returns_plan_and_flags_approval(
    workflows_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_user(db_session, role=OrganizationRole.viewer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await workflows_client.post(
        "/api/v1/agent/workflows/preview",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "workflow_type": "policy_comparison",
            "requested_actions": ["share"],
            "request": {
                "objective": "Compare the policies",
                "mode": "compare",
                "question": "Compare the policies",
                "document_query": "Compare the policies",
                "rerank": True,
                "budget": {"max_steps": 8, "max_tool_calls": 20},
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["workflow_type"] == "policy_comparison"
    assert payload["planner_strategy"] == "policy_lookup"
    assert payload["requires_approval"] is True
    assert payload["requested_actions"] == ["share"]
    assert len(payload["plan"]) >= 2
    assert payload["plan"][0]["tool_name"] == "search_documents"
    assert payload["plan"][-1]["tool_name"] == "compare_documents"


@pytest.mark.asyncio
async def test_workflow_preview_is_feature_gated(
    workflows_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_agents", False)
    user, organization = await _seed_user(db_session, role=OrganizationRole.viewer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await workflows_client.post(
        "/api/v1/agent/workflows/preview",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={"workflow_type": "audit_evidence_pack"},
    )

    assert response.status_code == 404
