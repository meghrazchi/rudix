"""Tests for F343: organization workflow memory and user preferences."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

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
from app.main import app
from app.models.enums import OrganizationRole
from app.models.org_memory import OrgWorkflow, UserMemoryPreference
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def org_memory_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_org_memory", True)
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
    role: OrganizationRole,
    org_name: str,
) -> tuple[User, Organization]:
    organization = Organization(
        name=org_name,
        slug=f"{org_name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
    )
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"{org_name.lower().replace(' ', '-')}-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@example.com",
        display_name=f"{org_name} User",
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


def _workflow_payload(
    *,
    role_scope: list[str] | None = None,
    query_template: str = "Find the latest policy summary",
) -> dict[str, object]:
    return {
        "name": "Audit evidence pack",
        "description": "Reusable audit workflow",
        "workflow_type": "audit_evidence_pack",
        "steps": [
            {
                "label": "Collect evidence",
                "query_template": query_template,
                "scope": "collection",
                "collection_ids": [str(uuid4())],
            }
        ],
        "role_scope": role_scope,
        "collection_scope_ids": [str(uuid4())],
    }


@pytest.mark.asyncio
async def test_feature_flag_blocks_memory_routes_when_disabled(
    org_memory_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_org_memory", False)
    user, organization = await _seed_user(
        db_session, role=OrganizationRole.admin, org_name="Disabled Org"
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await org_memory_client.get(
        "/api/v1/memory/workflows",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_org_workflow_crud_and_reuse_are_org_scoped(
    org_memory_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner, organization = await _seed_user(
        db_session, role=OrganizationRole.owner, org_name="Memory Org"
    )
    token = create_app_access_token(
        subject=owner.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    create_response = await org_memory_client.post(
        "/api/v1/memory/workflows",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json=_workflow_payload(role_scope=["owner", "admin"]),
    )
    assert create_response.status_code == 201
    first_workflow = create_response.json()
    workflow_id = first_workflow["workflow_id"]
    assert first_workflow["use_count"] == 0
    assert first_workflow["verified_knowledge_card_id"] is None

    second_response = await org_memory_client.post(
        "/api/v1/memory/workflows",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            **_workflow_payload(role_scope=["owner"]),
            "name": "Contract review",
        },
    )
    assert second_response.status_code == 201
    second_workflow_id = second_response.json()["workflow_id"]

    for _ in range(3):
        increment_response = await org_memory_client.post(
            f"/api/v1/memory/workflows/{workflow_id}/increment-use",
            headers=_auth_headers(token=token, organization_id=str(organization.id)),
        )
        assert increment_response.status_code == 204

    list_response = await org_memory_client.get(
        "/api/v1/memory/workflows",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 2
    assert list_payload["items"][0]["workflow_id"] == workflow_id
    assert list_payload["items"][1]["workflow_id"] == second_workflow_id

    detail_response = await org_memory_client.get(
        f"/api/v1/memory/workflows/{workflow_id}",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["use_count"] == 3

    update_response = await org_memory_client.patch(
        f"/api/v1/memory/workflows/{workflow_id}",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={"description": "Updated workflow description"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["description"] == "Updated workflow description"

    persisted = (
        await db_session.execute(select(OrgWorkflow).where(OrgWorkflow.id == UUID(workflow_id)))
    ).scalar_one()
    assert persisted.use_count == 3

    second_org_user, second_org = await _seed_user(
        db_session, role=OrganizationRole.admin, org_name="Other Org"
    )
    second_token = create_app_access_token(
        subject=second_org_user.external_auth_id,
        organization_id=str(second_org.id),
        expires_in_seconds=600,
    )

    cross_org_response = await org_memory_client.get(
        f"/api/v1/memory/workflows/{workflow_id}",
        headers=_auth_headers(token=second_token, organization_id=str(second_org.id)),
    )
    assert cross_org_response.status_code == 404

    archive_cross_org_response = await org_memory_client.post(
        f"/api/v1/admin/memory/workflows/{workflow_id}/archive",
        headers=_auth_headers(token=second_token, organization_id=str(second_org.id)),
    )
    assert archive_cross_org_response.status_code == 404

    member_user, member_org = await _seed_user(
        db_session, role=OrganizationRole.member, org_name="Member Org"
    )
    member_token = create_app_access_token(
        subject=member_user.external_auth_id,
        organization_id=str(member_org.id),
        expires_in_seconds=600,
    )
    member_create_response = await org_memory_client.post(
        "/api/v1/memory/workflows",
        headers=_auth_headers(token=member_token, organization_id=str(member_org.id)),
        json=_workflow_payload(role_scope=["owner"]),
    )
    assert member_create_response.status_code == 201
    member_workflow_id = member_create_response.json()["workflow_id"]

    member_archive_response = await org_memory_client.post(
        f"/api/v1/admin/memory/workflows/{member_workflow_id}/archive",
        headers=_auth_headers(token=member_token, organization_id=str(member_org.id)),
    )
    assert member_archive_response.status_code == 403

    member_delete_response = await org_memory_client.delete(
        f"/api/v1/admin/memory/workflows/{member_workflow_id}",
        headers=_auth_headers(token=member_token, organization_id=str(member_org.id)),
    )
    assert member_delete_response.status_code == 403

    member_list_response = await org_memory_client.get(
        "/api/v1/memory/workflows",
        headers=_auth_headers(token=member_token, organization_id=str(member_org.id)),
    )
    assert member_list_response.status_code == 200
    assert member_list_response.json()["total"] == 0


@pytest.mark.asyncio
async def test_org_memory_rejects_sensitive_templates_and_preferences(
    org_memory_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_user(
        db_session, role=OrganizationRole.admin, org_name="Redaction Org"
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    workflow_response = await org_memory_client.post(
        "/api/v1/memory/workflows",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json=_workflow_payload(query_template="Email alice@example.com for approval"),
    )
    assert workflow_response.status_code == 422

    preference_response = await org_memory_client.put(
        "/api/v1/memory/preferences",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "preferred_scope": "collection",
            "preferred_collection_ids": [str(uuid4())],
            "rag_profile_id": str(uuid4()),
            "answer_language": "en",
            "extra_defaults": {
                "review_notes": "Bearer secret-token",
            },
        },
    )
    assert preference_response.status_code == 422

    preference_create_response = await org_memory_client.put(
        "/api/v1/memory/preferences",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={
            "preferred_scope": "collection",
            "preferred_collection_ids": [str(uuid4())],
            "rag_profile_id": str(uuid4()),
            "answer_language": "en",
            "extra_defaults": {"default_role": "admin"},
        },
    )
    assert preference_create_response.status_code == 200
    preference_payload = preference_create_response.json()
    assert preference_payload["preferred_scope"] == "collection"
    assert preference_payload["extra_defaults"] == {"default_role": "admin"}

    preference_get_response = await org_memory_client.get(
        "/api/v1/memory/preferences",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert preference_get_response.status_code == 200
    assert preference_get_response.json()["preference_id"] == preference_payload["preference_id"]

    deleted_response = await org_memory_client.delete(
        "/api/v1/memory/preferences",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert deleted_response.status_code == 204

    missing_response = await org_memory_client.get(
        "/api/v1/memory/preferences",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert missing_response.status_code == 404

    persisted_preferences = (
        (
            await db_session.execute(
                select(UserMemoryPreference).where(
                    UserMemoryPreference.organization_id == organization.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert persisted_preferences == []
