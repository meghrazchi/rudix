from __future__ import annotations

import os
from uuid import UUID, uuid4

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
from app.auth.models import AuthenticatedPrincipal
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.agents.schemas import ToolCall, ToolEffectPolicy, ToolSpec, ToolSurface
from app.domains.agents.services import AgentRuntime, ToolRegistry
from app.interfaces.http import agent_runs as agent_runs_api
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def agent_runs_client(
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
    role: OrganizationRole = OrganizationRole.viewer,
) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Agent API Primary", slug=f"agent-api-primary-{uuid4().hex[:8]}")
    secondary_org = Organization(name="Agent API Secondary", slug=f"agent-api-secondary-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, secondary_org])
    await db_session.flush()

    user = User(
        organization_id=primary_org.id,
        external_auth_id=f"agent-api-user-{uuid4().hex[:8]}",
        email=f"agent-api-{uuid4().hex[:8]}@example.com",
        display_name="Agent API User",
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
    role: OrganizationRole = OrganizationRole.viewer,
) -> User:
    user = User(
        organization_id=organization.id,
        external_auth_id=f"agent-api-org-user-{uuid4().hex[:8]}",
        email=f"agent-api-org-{uuid4().hex[:8]}@example.com",
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


def _build_test_runtime() -> AgentRuntime:
    async def _search_documents(call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, object]:
        del principal
        return {
            "total": 1,
            "items": [
                {
                    "document_id": str(call.arguments.get("document_id", "11111111-1111-1111-1111-111111111111")),
                    "filename": "Policy.pdf",
                    "status": "indexed",
                }
            ],
        }

    async def _answer_from_context(call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, object]:
        del call, principal
        return {
            "response": "Grounded answer",
            "not_found": False,
            "citations": [],
            "confidence": {"score": 0.82, "category": "high"},
            "debug": {"usage": {"total_tokens": 42, "total_cost_usd": 0.0011}},
        }

    registry = ToolRegistry()
    registry.register_tool(
        spec=ToolSpec(
            name="search_documents",
            description="Search indexed documents",
            capability="documents.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=["viewer"],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
        ),
        handler=_search_documents,
    )
    registry.register_tool(
        spec=ToolSpec(
            name="answer_from_context",
            description="Answer from context",
            capability="documents.answer",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=["viewer"],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
        ),
        handler=_answer_from_context,
    )
    return AgentRuntime(registry=registry)


@pytest.mark.asyncio
async def test_create_and_get_agent_run_is_organization_scoped(
    agent_runs_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_runs_api, "agent_runtime", _build_test_runtime())
    user, organization, other_organization = await _seed_principal(db_session)
    other_user = await _seed_user_for_org(db_session, organization=other_organization)

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    create_response = await agent_runs_client.post(
        "/api/v1/agent/runs",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "agentic_mode": True,
            "request": {
                "objective": "Answer the policy question",
                "mode": "answer",
                "question": "What is the policy?",
            },
        },
    )
    assert create_response.status_code == 201
    create_payload = create_response.json()
    assert create_payload["run"]["status"] == "completed"
    run_id = create_payload["run"]["run_id"]
    assert UUID(run_id)

    detail_response = await agent_runs_client.get(
        f"/api/v1/agent/runs/{run_id}",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["run_id"] == run_id
    assert detail_payload["organization_id"] == str(organization.id)
    assert detail_payload["status"] == "completed"
    assert len(detail_payload["steps"]) >= 2
    assert len(detail_payload["tool_calls"]) >= 1

    other_token = create_app_access_token(
        subject=other_user.external_auth_id,
        organization_id=str(other_organization.id),
        expires_in_seconds=600,
    )
    forbidden_response = await agent_runs_client.get(
        f"/api/v1/agent/runs/{run_id}",
        headers=_auth_headers(token=other_token, organization_id=str(other_organization.id)),
    )
    assert forbidden_response.status_code == 404


@pytest.mark.asyncio
async def test_create_agent_run_requires_explicit_agentic_mode(
    agent_runs_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await agent_runs_client.post(
        "/api/v1/agent/runs",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "agentic_mode": False,
            "request": {"objective": "Answer the policy question"},
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "agentic_mode_required"


@pytest.mark.asyncio
async def test_create_agent_run_returns_safe_error_payload_on_runtime_failure(
    agent_runs_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, organization, _ = await _seed_principal(db_session)

    async def _raise_runtime_error(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("token=super-secret")

    monkeypatch.setattr(agent_runs_api.agent_runtime, "execute", _raise_runtime_error)

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await agent_runs_client.post(
        "/api/v1/agent/runs",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "agentic_mode": True,
            "request": {"objective": "Answer the policy question"},
        },
    )
    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["code"] == "agent_runtime_unavailable"
    assert payload["detail"]["message"] == "Unable to execute agent run. Retry shortly."
    assert payload["detail"].get("request_id")
    assert "token" not in str(payload["detail"]).lower()
