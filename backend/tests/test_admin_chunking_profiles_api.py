import os
from collections.abc import Sequence
from typing import Any
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
from app.domains.documents.chunking.protocol import ChunkPayload, PageLike
from app.interfaces.http import documents as documents_api
from app.main import app
from app.models.chunking_profile import OrganizationChunkingProfile
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


class FakeTaskResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class FakeReindexTask:
    def __init__(self) -> None:
        self.delay_calls: list[dict[str, Any]] = []

    def delay(self, document_id: str, **kwargs: Any) -> FakeTaskResult:
        self.delay_calls.append({"document_id": document_id, **kwargs})
        return FakeTaskResult(task_id=f"reindex-task-{len(self.delay_calls)}")


@pytest_asyncio.fixture
async def profile_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "feature_enable_chunking_profiles", True)
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
        name=f"Chunking Org {uuid4().hex[:6]}",
        slug=f"chunking-org-{uuid4().hex[:8]}",
    )
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"chunking-user-{uuid4().hex[:8]}",
        email=f"chunking-{uuid4().hex[:8]}@example.com",
        display_name="Chunking User",
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


# ---------------------------------------------------------------------------
# Strategy catalog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_strategies_returns_catalog(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await profile_client.get(
        "/api/v1/admin/chunking-profiles/strategies",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["strategies"], list)
    assert len(payload["strategies"]) > 0
    names = {s["name"] for s in payload["strategies"]}
    assert "token_recursive" in names
    assert "adaptive_hybrid" in names
    assert "default_config" in payload
    assert payload["default_config"]["strategy"] == "token_recursive"
    assert "feature_chunking_profiles_enabled" in payload


@pytest.mark.asyncio
async def test_list_strategies_requires_admin_role(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await profile_client.get(
        "/api/v1/admin/chunking-profiles/strategies",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Feature flag guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_profiles_blocked_when_feature_disabled(
    profile_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_chunking_profiles", False)
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await profile_client.get(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_profile_persists_and_audits(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "My Token Profile",
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 800,
                "chunk_overlap_tokens": 150,
            },
            "set_as_default": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "My Token Profile"
    assert payload["slug"] == "my-token-profile"
    assert payload["config"]["strategy"] == "token_recursive"
    assert payload["config"]["chunk_size_tokens"] == 800
    assert payload["is_default"] is True
    assert payload["is_system"] is False
    assert payload["organization_id"] == str(org.id)

    stored = await db_session.scalar(
        select(OrganizationChunkingProfile).where(
            OrganizationChunkingProfile.organization_id == org.id,
            OrganizationChunkingProfile.slug == "my-token-profile",
        )
    )
    assert stored is not None
    assert stored.is_default is True

    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.organization_id == org.id,
            AuditLog.action == "admin.chunking_profile.created",
        )
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_create_profile_overlap_gte_size_returns_422(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Bad Profile",
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 500,
                "chunk_overlap_tokens": 500,
            },
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_profile_unknown_strategy_returns_422(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Bad Strategy",
            "config": {
                "strategy": "does_not_exist",
                "chunk_size_tokens": 500,
                "chunk_overlap_tokens": 100,
            },
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_profile_duplicate_slug_returns_409(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    for _ in range(2):
        response = await profile_client.post(
            "/api/v1/admin/chunking-profiles",
            headers=_auth_headers(token=token, organization_id=str(org.id)),
            json={
                "name": "Dup Profile",
                "slug": "dup-profile",
                "config": {
                    "strategy": "token_recursive",
                    "chunk_size_tokens": 700,
                    "chunk_overlap_tokens": 120,
                },
            },
        )

    assert response.status_code == 409


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_profiles_returns_org_scoped_results(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_principal(db_session, role=OrganizationRole.admin)
    user_b, org_b = await _seed_principal(db_session, role=OrganizationRole.admin)

    token_a = create_app_access_token(
        subject=user_a.external_auth_id,
        organization_id=str(org_a.id),
        expires_in_seconds=600,
    )
    token_b = create_app_access_token(
        subject=user_b.external_auth_id,
        organization_id=str(org_b.id),
        expires_in_seconds=600,
    )

    await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token_a, organization_id=str(org_a.id)),
        json={
            "name": "Org A Profile",
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 700,
                "chunk_overlap_tokens": 100,
            },
        },
    )

    response = await profile_client.get(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token_b, organization_id=str(org_b.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 0
    assert payload["profiles"] == []


@pytest.mark.asyncio
async def test_list_profiles_shows_default_first(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Not Default",
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 700,
                "chunk_overlap_tokens": 100,
            },
        },
    )
    await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Default Profile",
            "config": {
                "strategy": "paragraph_recursive",
                "chunk_size_tokens": 600,
                "chunk_overlap_tokens": 80,
            },
            "set_as_default": True,
        },
    )

    response = await profile_client.get(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["has_org_default"] is True
    assert payload["profiles"][0]["is_default"] is True


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_profile_returns_correct_data(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    create_response = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Get Test",
            "config": {
                "strategy": "sentence_window",
                "chunk_size_tokens": 400,
                "chunk_overlap_tokens": 50,
            },
        },
    )
    profile_id = create_response.json()["profile_id"]

    response = await profile_client.get(
        f"/api/v1/admin/chunking-profiles/{profile_id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_id"] == profile_id
    assert payload["config"]["strategy"] == "sentence_window"


@pytest.mark.asyncio
async def test_get_profile_from_other_org_returns_404(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_principal(db_session, role=OrganizationRole.admin)
    user_b, org_b = await _seed_principal(db_session, role=OrganizationRole.admin)

    token_a = create_app_access_token(
        subject=user_a.external_auth_id, organization_id=str(org_a.id), expires_in_seconds=600
    )
    token_b = create_app_access_token(
        subject=user_b.external_auth_id, organization_id=str(org_b.id), expires_in_seconds=600
    )

    create_response = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token_a, organization_id=str(org_a.id)),
        json={
            "name": "Private Profile",
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 700,
                "chunk_overlap_tokens": 100,
            },
        },
    )
    profile_id = create_response.json()["profile_id"]

    response = await profile_client.get(
        f"/api/v1/admin/chunking-profiles/{profile_id}",
        headers=_auth_headers(token=token_b, organization_id=str(org_b.id)),
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_profile_changes_config_and_audits(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    create_response = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Original",
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 700,
                "chunk_overlap_tokens": 120,
            },
        },
    )
    profile_id = create_response.json()["profile_id"]

    update_response = await profile_client.put(
        f"/api/v1/admin/chunking-profiles/{profile_id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Updated Name",
            "config": {
                "strategy": "heading_aware",
                "chunk_size_tokens": 500,
                "chunk_overlap_tokens": 80,
            },
        },
    )

    assert update_response.status_code == 200
    payload = update_response.json()
    assert payload["name"] == "Updated Name"
    assert payload["config"]["strategy"] == "heading_aware"

    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.organization_id == org.id,
            AuditLog.action == "admin.chunking_profile.updated",
        )
    )
    assert audit is not None


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_profile_removes_row_and_audits(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    create_response = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "To Delete",
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 700,
                "chunk_overlap_tokens": 100,
            },
        },
    )
    profile_id = create_response.json()["profile_id"]

    del_response = await profile_client.delete(
        f"/api/v1/admin/chunking-profiles/{profile_id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert del_response.status_code == 204

    from uuid import UUID as _UUID

    still_there = await db_session.scalar(
        select(OrganizationChunkingProfile).where(
            OrganizationChunkingProfile.id == _UUID(profile_id)
        )
    )
    assert still_there is None

    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.organization_id == org.id,
            AuditLog.action == "admin.chunking_profile.deleted",
        )
    )
    assert audit is not None


# ---------------------------------------------------------------------------
# Set-default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_default_clears_previous_default(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    resp_a = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Alpha",
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 700,
                "chunk_overlap_tokens": 100,
            },
            "set_as_default": True,
        },
    )
    resp_b = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Beta",
            "config": {
                "strategy": "paragraph_recursive",
                "chunk_size_tokens": 600,
                "chunk_overlap_tokens": 80,
            },
        },
    )
    id_a = resp_a.json()["profile_id"]
    id_b = resp_b.json()["profile_id"]

    set_resp = await profile_client.post(
        f"/api/v1/admin/chunking-profiles/{id_b}/set-default",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["is_default"] is True

    from uuid import UUID as _UUID

    old_default = await db_session.get(OrganizationChunkingProfile, _UUID(id_a))
    new_default = await db_session.get(OrganizationChunkingProfile, _UUID(id_b))
    assert old_default is not None
    assert old_default.is_default is False
    assert new_default is not None
    assert new_default.is_default is True

    audit = await db_session.scalar(
        select(AuditLog).where(
            AuditLog.organization_id == org.id,
            AuditLog.action == "admin.chunking_profile.default_set",
        )
    )
    assert audit is not None


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_stats_without_raw_text(
    profile_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeStrategy:
        last_selection = None

        async def chunk(
            self,
            *,
            document_id: UUID,
            pages: Sequence[PageLike],
        ) -> list[ChunkPayload]:
            del pages
            return [
                ChunkPayload(
                    document_id=document_id,
                    page_number=1,
                    chunk_index=0,
                    text="chunk one",
                    token_count=80,
                    embedding_model="test-embedding-model",
                    index_version="v-test",
                    strategy_name="token_recursive",
                ),
                ChunkPayload(
                    document_id=document_id,
                    page_number=1,
                    chunk_index=1,
                    text="chunk two",
                    token_count=72,
                    embedding_model="test-embedding-model",
                    index_version="v-test",
                    strategy_name="token_recursive",
                ),
            ]

    class _FakeRegistry:
        def known_strategies(self) -> list[str]:
            return ["token_recursive"]

        def resolve(self, *args: object, **kwargs: object) -> _FakeStrategy:
            del args, kwargs
            return _FakeStrategy()

    monkeypatch.setattr(
        "app.domains.documents.chunking.registry.get_registry",
        lambda: _FakeRegistry(),
    )

    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    sample = (
        "Artificial intelligence is transforming every industry. "
        "Machine learning models can now process vast amounts of data quickly. "
        "Natural language processing enables computers to understand human speech. "
        "Computer vision systems can identify objects in images and videos. "
        "Reinforcement learning allows agents to learn from trial and error. "
    ) * 20

    response = await profile_client.post(
        "/api/v1/admin/chunking-profiles/preview",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 150,
                "chunk_overlap_tokens": 20,
            },
            "sample_text": sample,
            "file_type": "txt",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chunk_count"] > 0
    assert payload["min_tokens"] > 0
    assert payload["max_tokens"] >= payload["min_tokens"]
    assert payload["total_tokens"] > 0
    assert payload["strategy_used"] == "token_recursive"
    assert payload["reason_codes"] == []

    for chunk_meta in payload["sample_chunks"]:
        assert "token_count" in chunk_meta
        assert "chunk_index" in chunk_meta
        assert "text" not in chunk_meta, "Preview must never return raw chunk text"


@pytest.mark.asyncio
async def test_preview_invalid_config_returns_422(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await profile_client.post(
        "/api/v1/admin/chunking-profiles/preview",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "config": {
                "strategy": "token_recursive",
                "chunk_size_tokens": 200,
                "chunk_overlap_tokens": 300,
            },
            "sample_text": "Some text here.",
        },
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Reindex with profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reindex_with_inline_profile_passes_config_to_task(
    profile_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    document = Document(
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="test.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="test/test.pdf",
        status=DocumentStatus.indexed.value,
    )
    db_session.add(document)
    await db_session.commit()

    fake_task = FakeReindexTask()
    monkeypatch.setattr(documents_api, "reindex_document_task", fake_task)

    response = await profile_client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "chunking_profile_config": {
                "strategy": "heading_aware",
                "chunk_size_tokens": 600,
                "chunk_overlap_tokens": 80,
            }
        },
    )

    assert response.status_code == 202
    assert len(fake_task.delay_calls) == 1
    call = fake_task.delay_calls[0]
    assert call["document_id"] == str(document.id)
    assert call["chunking_profile_config"]["strategy"] == "heading_aware"
    assert call["chunking_profile_config"]["chunk_size_tokens"] == 600


@pytest.mark.asyncio
async def test_reindex_with_profile_id_passes_config_to_task(
    profile_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.owner)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    create_resp = await profile_client.post(
        "/api/v1/admin/chunking-profiles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Reindex Profile",
            "config": {
                "strategy": "paragraph_recursive",
                "chunk_size_tokens": 550,
                "chunk_overlap_tokens": 75,
            },
        },
    )
    profile_id = create_resp.json()["profile_id"]

    document = Document(
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="report.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="test/report.pdf",
        status=DocumentStatus.indexed.value,
    )
    db_session.add(document)
    await db_session.commit()

    fake_task = FakeReindexTask()
    monkeypatch.setattr(documents_api, "reindex_document_task", fake_task)

    response = await profile_client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"chunking_profile_id": profile_id},
    )

    assert response.status_code == 202
    assert len(fake_task.delay_calls) == 1
    call = fake_task.delay_calls[0]
    assert call["chunking_profile_config"]["strategy"] == "paragraph_recursive"
    assert call["chunking_profile_config"]["chunk_size_tokens"] == 550


@pytest.mark.asyncio
async def test_reindex_with_both_profile_id_and_config_returns_422(
    profile_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    import pytest as _pytest

    from app.domains.admin.schemas.chunking_profiles import ReindexWithProfileRequest

    with _pytest.raises(Exception) as exc_info:
        ReindexWithProfileRequest(
            chunking_profile_id=str(uuid4()),
            chunking_profile_config={
                "strategy": "token_recursive",
                "chunk_size_tokens": 700,
                "chunk_overlap_tokens": 100,
            },
        )
    assert exc_info is not None
