"""Backend tests for F328: Saved answer library — deprecate, restore, duplicate.

Covers:
  A. Repository — deprecate() sets status=deprecated and deprecated_at
  B. Repository — restore() resets status=draft and snapshots a version
  C. Repository — duplicate() creates a copy with citations
  D. HTTP — POST /{id}/deprecate transitions published card
  E. HTTP — POST /{id}/deprecate rejects already-deprecated card (409)
  F. HTTP — POST /{id}/deprecate requires admin role (403 for member)
  G. HTTP — POST /{id}/restore transitions archived card to draft
  H. HTTP — POST /{id}/restore transitions deprecated card to draft
  I. HTTP — POST /{id}/restore rejects active card (409)
  J. HTTP — POST /{id}/duplicate creates a draft copy
  K. HTTP — duplicate preserves citations count
  L. HTTP — deprecated card excluded from search/match results
  M. HTTP — GET list with status=deprecated filter
  N. HTTP — VerifiedAnswerResponse includes deprecated_at and restored_at

Run:
    pytest tests/test_knowledge_cards_f328.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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

from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.verified_answers.repositories.verified_answers import VerifiedAnswerRepository
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.models.verified_answer import VerifiedAnswer

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db(db_session: AsyncSession) -> AsyncSession:
    return db_session


def _make_token(user_id: str, org_id: str, role: str) -> str:
    settings.auth_provider = AuthProvider.app
    return create_app_access_token(user_id=user_id, organization_id=org_id, role=role)


@pytest_asyncio.fixture
async def org(db: AsyncSession) -> Organization:
    o = Organization(name="F328Org", slug=f"f328-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"admin-f328-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db.flush()
    token = _make_token(str(u.id), str(org.id), OrganizationRole.admin.value)
    return u, token


@pytest_asyncio.fixture
async def member_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"member-f328-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.member.value,
        )
    )
    await db.flush()
    token = _make_token(str(u.id), str(org.id), OrganizationRole.member.value)
    return u, token


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override():
        yield db

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


_repo = VerifiedAnswerRepository()


async def _create_draft(
    db: AsyncSession, org_id, user_id, *, question: str = "What is X?", title: str = "Card"
) -> VerifiedAnswer:
    answer = await _repo.create(
        db,
        organization_id=org_id,
        title=title,
        question=question,
        answer_text="The answer is X.",
        tags=None,
        collection_id=None,
        owner_id=user_id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user_id,
    )
    await db.flush()
    return answer


async def _publish_card(db: AsyncSession, answer: VerifiedAnswer) -> None:
    await _repo.set_status(db, answer, "pending_review")
    await _repo.approve(db, answer, approved_by_id=answer.owner_id, note=None)
    await _repo.publish(db, answer)
    await db.flush()


# ---------------------------------------------------------------------------
# A. Repository — deprecate()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_deprecate_sets_status_and_timestamp(
    db: AsyncSession, org: Organization, admin_user: tuple
) -> None:
    user, _ = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _publish_card(db, card)

    before = datetime.now(UTC)
    await _repo.deprecate(db, card)

    assert card.status == "deprecated"
    assert card.deprecated_at is not None
    assert card.deprecated_at >= before


# ---------------------------------------------------------------------------
# B. Repository — restore()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_restore_reverts_archived_to_draft(
    db: AsyncSession, org: Organization, admin_user: tuple
) -> None:
    user, _ = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _repo.archive(db, card)
    assert card.status == "archived"

    await _repo.restore(db, card, restored_by_id=user.id)
    assert card.status == "draft"
    assert card.restored_at is not None


@pytest.mark.asyncio
async def test_b2_restore_snapshots_version(
    db: AsyncSession, org: Organization, admin_user: tuple
) -> None:
    user, _ = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _repo.archive(db, card)
    initial_version_count = len(card.versions)

    await _repo.restore(db, card, restored_by_id=user.id)
    await db.flush()
    versions = await _repo.list_versions(db, answer_id=card.id, organization_id=org.id)

    assert len(versions) > initial_version_count
    assert any(v.change_reason == "restored_from_archive" for v in versions)


# ---------------------------------------------------------------------------
# C. Repository — duplicate()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_duplicate_creates_draft_copy(
    db: AsyncSession, org: Organization, admin_user: tuple
) -> None:
    user, _ = admin_user
    source = await _create_draft(db, org.id, user.id, title="Original")
    await _publish_card(db, source)

    copy = await _repo.duplicate(db, source, created_by_id=user.id)
    await db.flush()

    assert copy.id != source.id
    assert copy.status == "draft"
    assert "Original" in copy.title
    assert copy.question == source.question
    assert copy.answer_text == source.answer_text
    assert copy.organization_id == source.organization_id


# ---------------------------------------------------------------------------
# D. HTTP — POST /{id}/deprecate transitions published card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d_http_deprecate_published_card(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _publish_card(db, card)
    await db.commit()

    resp = await client.post(
        f"/verified-answers/{card.id}/deprecate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "deprecated"
    assert data["deprecated_at"] is not None


# ---------------------------------------------------------------------------
# E. HTTP — POST /{id}/deprecate rejects already-deprecated card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e_http_deprecate_already_deprecated(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _publish_card(db, card)
    await _repo.deprecate(db, card)
    await db.commit()

    resp = await client.post(
        f"/verified-answers/{card.id}/deprecate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# F. HTTP — deprecate requires admin (member → 403)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f_http_deprecate_member_forbidden(
    db: AsyncSession, org: Organization, admin_user: tuple, member_user: tuple, client: AsyncClient
) -> None:
    admin, _ = admin_user
    _, member_token = member_user
    card = await _create_draft(db, org.id, admin.id)
    await _publish_card(db, card)
    await db.commit()

    resp = await client.post(
        f"/verified-answers/{card.id}/deprecate",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# G. HTTP — POST /{id}/restore transitions archived card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g_http_restore_archived_card(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _repo.archive(db, card)
    await db.commit()

    resp = await client.post(
        f"/verified-answers/{card.id}/restore",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "draft"
    assert data["restored_at"] is not None


# ---------------------------------------------------------------------------
# H. HTTP — POST /{id}/restore transitions deprecated card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_http_restore_deprecated_card(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _publish_card(db, card)
    await _repo.deprecate(db, card)
    await db.commit()

    resp = await client.post(
        f"/verified-answers/{card.id}/restore",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"


# ---------------------------------------------------------------------------
# I. HTTP — POST /{id}/restore rejects active (non-archived) card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_i_http_restore_active_card_rejected(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id)
    await db.commit()

    resp = await client.post(
        f"/verified-answers/{card.id}/restore",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# J. HTTP — POST /{id}/duplicate creates a draft copy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_j_http_duplicate_card(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id, title="Source Card")
    await db.commit()

    resp = await client.post(
        f"/verified-answers/{card.id}/duplicate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["answer_id"] != str(card.id)
    assert "Source Card" in data["title"]


# ---------------------------------------------------------------------------
# K. HTTP — duplicate preserves citations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k_http_duplicate_copies_citations(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    from app.models.document import Document

    user, token = admin_user
    # Create a dummy document so the FK is valid.
    doc = Document(
        organization_id=org.id,
        title="Doc",
        filename="doc.pdf",
        status="indexed",
        source_type="upload",
    )
    db.add(doc)
    await db.flush()

    card = await _create_draft(db, org.id, user.id)
    await _repo.replace_citations(
        db,
        card,
        [{"document_id": str(doc.id), "chunk_id": None, "text_snippet": "snippet", "page_number": 1, "citation_order": 0}],
    )
    await db.commit()

    resp = await client.post(
        f"/verified-answers/{card.id}/duplicate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["citations"]) == 1


# ---------------------------------------------------------------------------
# L. HTTP — deprecated card excluded from search/match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_deprecated_excluded_from_search(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id, question="What is deprecation?", title="Dep card")
    await _publish_card(db, card)
    await _repo.deprecate(db, card)
    await db.commit()

    resp = await client.get(
        "/verified-answers/search/match",
        params={"query": "What is deprecation?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    ids = [item["answer_id"] for item in resp.json()["items"]]
    assert str(card.id) not in ids


# ---------------------------------------------------------------------------
# M. HTTP — list with status=deprecated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_http_list_deprecated_filter(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _publish_card(db, card)
    await _repo.deprecate(db, card)
    await db.commit()

    resp = await client.get(
        "/verified-answers",
        params={"status": "deprecated"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(item["status"] == "deprecated" for item in data["items"])


# ---------------------------------------------------------------------------
# N. HTTP — response includes new fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n_response_includes_new_fields(
    db: AsyncSession, org: Organization, admin_user: tuple, client: AsyncClient
) -> None:
    user, token = admin_user
    card = await _create_draft(db, org.id, user.id)
    await _publish_card(db, card)
    await db.commit()

    resp = await client.get(
        f"/verified-answers/{card.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "deprecated_at" in data
    assert "restored_at" in data
    assert data["deprecated_at"] is None
    assert data["restored_at"] is None
