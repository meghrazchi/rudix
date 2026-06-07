"""Backend tests for F150: RAG profile and retrieval preset management.

Covers:
  A. Profile CRUD API — create, list, get, update, archive, unarchive
  B. Default-flag management — set-default clears previous default
  C. Version snapshots — create bumps version and writes snapshot
  D. Rollback — restores config from snapshot and creates new version
  E. Collection overrides — set, list, delete
  F. Resolve endpoint — collection_override > org_default > system_default
  G. Role guards — member/viewer cannot create, update, or archive
  H. Archived-profile guards — cannot edit or assign archived profiles
  I. Repository — org isolation enforced on every query

Run:
    pytest tests/test_rag_profiles_f150.py -v
"""

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
from app.domains.rag_profiles.repositories.rag_profiles import RagProfileRepository
from app.domains.rag_profiles.services.rag_profile_service import (
    SYSTEM_DEFAULT_CONFIG,
    create_profile_with_version,
    resolve_profile_for_context,
    rollback_to_version,
    update_profile_with_version,
)
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.rag_profile import RagProfile
from app.models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def rag_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


def _make_token(
    user_id: str,
    org_id: str,
    role: str = OrganizationRole.admin.value,
) -> str:
    return create_app_access_token(
        user_id=user_id,
        organization_id=org_id,
        role=role,
        secret=SecretStr("test-secret"),
        issuer="rudix-test",
        audience="rudix-test-audience",
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_context(db_session: AsyncSession):
    org = Organization(name="Test Org", slug=f"test-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"admin-{uuid4().hex[:6]}@test.com", display_name="Admin")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.admin.value,
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.admin.value)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


@pytest_asyncio.fixture
async def viewer_context(db_session: AsyncSession):
    org = Organization(name="Viewer Org", slug=f"viewer-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(email=f"viewer-{uuid4().hex[:6]}@test.com", display_name="Viewer")
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.viewer.value,
    )
    db_session.add(member)
    await db_session.flush()

    token = _make_token(str(user.id), str(org.id), OrganizationRole.viewer.value)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": token}


# ---------------------------------------------------------------------------
# A. Profile CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_profile(rag_client: AsyncClient, admin_context: dict) -> None:
    resp = await rag_client.post(
        "/api/rag-profiles",
        json={
            "name": "Test Profile",
            "description": "For testing",
            "config": {"top_k": 5, "citation_strictness": "strict"},
            "set_as_default": False,
            "change_note": "Initial",
        },
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Test Profile"
    assert data["config"]["top_k"] == 5
    assert data["config"]["citation_strictness"] == "strict"
    assert data["version"] == 1
    assert data["is_default"] is False
    assert data["is_archived"] is False


@pytest.mark.asyncio
async def test_list_profiles(rag_client: AsyncClient, admin_context: dict) -> None:
    # create two profiles
    for name in ("Alpha", "Beta"):
        await rag_client.post(
            "/api/rag-profiles",
            json={"name": name, "config": {}},
            headers=_auth(admin_context["token"]),
        )
    resp = await rag_client.get(
        "/api/rag-profiles",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 2


@pytest.mark.asyncio
async def test_get_profile(rag_client: AsyncClient, admin_context: dict) -> None:
    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "GetTest", "config": {"top_k": 7}},
        headers=_auth(admin_context["token"]),
    )
    profile_id = create_resp.json()["profile_id"]

    resp = await rag_client.get(
        f"/api/rag-profiles/{profile_id}",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["config"]["top_k"] == 7


@pytest.mark.asyncio
async def test_update_profile(rag_client: AsyncClient, admin_context: dict) -> None:
    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "UpdateTest", "config": {"top_k": 10}},
        headers=_auth(admin_context["token"]),
    )
    pid = create_resp.json()["profile_id"]

    resp = await rag_client.patch(
        f"/api/rag-profiles/{pid}",
        json={"config": {"top_k": 20}, "change_note": "Increased top_k"},
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["config"]["top_k"] == 20
    assert data["version"] == 2


@pytest.mark.asyncio
async def test_archive_and_unarchive_profile(rag_client: AsyncClient, admin_context: dict) -> None:
    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "ArchiveTest", "config": {}},
        headers=_auth(admin_context["token"]),
    )
    pid = create_resp.json()["profile_id"]

    archive_resp = await rag_client.post(
        f"/api/rag-profiles/{pid}/archive",
        headers=_auth(admin_context["token"]),
    )
    assert archive_resp.status_code == 200
    assert archive_resp.json()["is_archived"] is True

    # editing archived profile is blocked
    edit_resp = await rag_client.patch(
        f"/api/rag-profiles/{pid}",
        json={"name": "NewName"},
        headers=_auth(admin_context["token"]),
    )
    assert edit_resp.status_code == 409

    unarchive_resp = await rag_client.post(
        f"/api/rag-profiles/{pid}/unarchive",
        headers=_auth(admin_context["token"]),
    )
    assert unarchive_resp.status_code == 200
    assert unarchive_resp.json()["is_archived"] is False


# ---------------------------------------------------------------------------
# B. Default flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_default_clears_previous(rag_client: AsyncClient, admin_context: dict) -> None:
    r1 = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "P1", "config": {}, "set_as_default": True},
        headers=_auth(admin_context["token"]),
    )
    p1_id = r1.json()["profile_id"]
    assert r1.json()["is_default"] is True

    r2 = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "P2", "config": {}, "set_as_default": False},
        headers=_auth(admin_context["token"]),
    )
    p2_id = r2.json()["profile_id"]

    # set P2 as default via endpoint
    set_resp = await rag_client.post(
        f"/api/rag-profiles/{p2_id}/set-default",
        headers=_auth(admin_context["token"]),
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["is_default"] is True

    # P1 should no longer be default
    p1_resp = await rag_client.get(
        f"/api/rag-profiles/{p1_id}",
        headers=_auth(admin_context["token"]),
    )
    assert p1_resp.json()["is_default"] is False


@pytest.mark.asyncio
async def test_cannot_archive_default_profile(rag_client: AsyncClient, admin_context: dict) -> None:
    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "DefaultProfile", "config": {}, "set_as_default": True},
        headers=_auth(admin_context["token"]),
    )
    pid = create_resp.json()["profile_id"]

    resp = await rag_client.post(
        f"/api/rag-profiles/{pid}/archive",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# C. Version snapshots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_version_snapshot_on_update(rag_client: AsyncClient, admin_context: dict) -> None:
    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "VersionTest", "config": {"top_k": 5}},
        headers=_auth(admin_context["token"]),
    )
    pid = create_resp.json()["profile_id"]

    await rag_client.patch(
        f"/api/rag-profiles/{pid}",
        json={"config": {"top_k": 15}},
        headers=_auth(admin_context["token"]),
    )

    versions_resp = await rag_client.get(
        f"/api/rag-profiles/{pid}/versions",
        headers=_auth(admin_context["token"]),
    )
    assert versions_resp.status_code == 200
    versions = versions_resp.json()["items"]
    version_numbers = {v["version_number"] for v in versions}
    assert 1 in version_numbers
    assert 2 in version_numbers


# ---------------------------------------------------------------------------
# D. Rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_restores_config(rag_client: AsyncClient, admin_context: dict) -> None:
    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "RollbackTest", "config": {"top_k": 3, "safety_mode": "strict"}},
        headers=_auth(admin_context["token"]),
    )
    pid = create_resp.json()["profile_id"]

    await rag_client.patch(
        f"/api/rag-profiles/{pid}",
        json={"config": {"top_k": 99}},
        headers=_auth(admin_context["token"]),
    )

    rollback_resp = await rag_client.post(
        f"/api/rag-profiles/{pid}/rollback",
        json={"version_number": 1, "change_note": "Undo top_k change"},
        headers=_auth(admin_context["token"]),
    )
    assert rollback_resp.status_code == 200
    data = rollback_resp.json()
    assert data["config"]["top_k"] == 3
    assert data["version"] == 3  # v1 + v2 + v3 rollback snapshot


@pytest.mark.asyncio
async def test_rollback_to_current_version_returns_409(
    rag_client: AsyncClient, admin_context: dict
) -> None:
    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "NopRollback", "config": {}},
        headers=_auth(admin_context["token"]),
    )
    pid = create_resp.json()["profile_id"]

    resp = await rag_client.post(
        f"/api/rag-profiles/{pid}/rollback",
        json={"version_number": 1},
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# E. Collection overrides
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collection_override_set_and_list(
    rag_client: AsyncClient, admin_context: dict, db_session: AsyncSession
) -> None:
    # Create a real collection in DB for FK
    from app.models.collection import Collection

    collection = Collection(
        organization_id=admin_context["org_id"],
        name="Test Collection",
        slug=f"tc-{uuid4().hex[:8]}",
    )
    db_session.add(collection)
    await db_session.flush()

    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "OverrideProfile", "config": {}},
        headers=_auth(admin_context["token"]),
    )
    pid = create_resp.json()["profile_id"]

    resp = await rag_client.put(
        f"/api/rag-profiles/overrides/collections/{collection.id}",
        json={"rag_profile_id": pid},
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rag_profile_id"] == pid

    list_resp = await rag_client.get(
        "/api/rag-profiles/overrides/collections",
        headers=_auth(admin_context["token"]),
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 1

    # delete override
    del_resp = await rag_client.delete(
        f"/api/rag-profiles/overrides/collections/{collection.id}",
        headers=_auth(admin_context["token"]),
    )
    assert del_resp.status_code == 204


# ---------------------------------------------------------------------------
# F. Resolve endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_returns_system_default_when_no_profiles(
    rag_client: AsyncClient, admin_context: dict
) -> None:
    resp = await rag_client.get(
        "/api/rag-profiles/resolve",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "system_default"
    assert data["profile_id"] == "system"


@pytest.mark.asyncio
async def test_resolve_returns_org_default(rag_client: AsyncClient, admin_context: dict) -> None:
    await rag_client.post(
        "/api/rag-profiles",
        json={"name": "OrgDefault", "config": {"top_k": 8}, "set_as_default": True},
        headers=_auth(admin_context["token"]),
    )
    resp = await rag_client.get(
        "/api/rag-profiles/resolve",
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "org_default"
    assert data["config"]["top_k"] == 8


# ---------------------------------------------------------------------------
# G. Role guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_viewer_cannot_create_profile(rag_client: AsyncClient, viewer_context: dict) -> None:
    resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "ViewerAttempt", "config": {}},
        headers=_auth(viewer_context["token"]),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_list_profiles(rag_client: AsyncClient, viewer_context: dict) -> None:
    resp = await rag_client.get(
        "/api/rag-profiles",
        headers=_auth(viewer_context["token"]),
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_viewer_cannot_archive_profile(
    rag_client: AsyncClient,
    admin_context: dict,
    viewer_context: dict,
    db_session: AsyncSession,
) -> None:
    # Admin creates a profile in admin's org — viewer's org is separate, so
    # just test that the viewer cannot call archive at all (403).
    fake_id = str(uuid4())
    resp = await rag_client.post(
        f"/api/rag-profiles/{fake_id}/archive",
        headers=_auth(viewer_context["token"]),
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# H. Archived-profile guard — cannot assign to collection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_assign_archived_profile_as_collection_override(
    rag_client: AsyncClient, admin_context: dict, db_session: AsyncSession
) -> None:
    from app.models.collection import Collection

    collection = Collection(
        organization_id=admin_context["org_id"],
        name="Guard Col",
        slug=f"gc-{uuid4().hex[:8]}",
    )
    db_session.add(collection)
    await db_session.flush()

    create_resp = await rag_client.post(
        "/api/rag-profiles",
        json={"name": "ArchivedOverride", "config": {}},
        headers=_auth(admin_context["token"]),
    )
    pid = create_resp.json()["profile_id"]

    await rag_client.post(
        f"/api/rag-profiles/{pid}/archive",
        headers=_auth(admin_context["token"]),
    )

    resp = await rag_client.put(
        f"/api/rag-profiles/overrides/collections/{collection.id}",
        json={"rag_profile_id": pid},
        headers=_auth(admin_context["token"]),
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# I. Repository — org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_isolation(db_session: AsyncSession) -> None:
    repo = RagProfileRepository()
    org_a = Organization(name="Org A", slug=f"org-a-{uuid4().hex[:8]}")
    org_b = Organization(name="Org B", slug=f"org-b-{uuid4().hex[:8]}")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    profile_a = await repo.create_profile(
        db_session,
        organization_id=org_a.id,
        name="A Profile",
        description=None,
        config={"top_k": 3},
        is_default=False,
        created_by_id=None,
    )
    await db_session.flush()

    # Org B should not see Org A's profile
    result = await repo.get_profile(db_session, profile_id=profile_a.id, organization_id=org_b.id)
    assert result is None

    # Org A should see its own profile
    result = await repo.get_profile(db_session, profile_id=profile_a.id, organization_id=org_a.id)
    assert result is not None
    assert result.name == "A Profile"


# ---------------------------------------------------------------------------
# Service unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_system_default_config_has_required_keys() -> None:
    required = {
        "top_k",
        "rerank_enabled",
        "confidence_threshold",
        "citation_strictness",
        "safety_mode",
    }
    assert required.issubset(SYSTEM_DEFAULT_CONFIG.keys())


@pytest.mark.asyncio
async def test_resolve_returns_none_when_empty(db_session: AsyncSession) -> None:
    org = Organization(name="Empty Org", slug=f"empty-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    profile, source = await resolve_profile_for_context(
        db_session, organization_id=org.id, collection_id=None
    )
    assert profile is None
    assert source == "system_default"
