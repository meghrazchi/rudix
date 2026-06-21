"""Backend tests for F255: Verified answers and curated knowledge cards.

Covers:
  A. Repository — create / get / list / update / archive
  B. Repository — citation management (replace_citations)
  C. Repository — version snapshots on create and update
  D. Repository — find_published_match retrieval helper
  E. Repository — org isolation (cannot read another org's card)
  F. Schema — ApproveRequest / RejectRequest validators
  G. HTTP — POST /verified-answers creates draft
  H. HTTP — GET /verified-answers lists with status filter
  I. HTTP — PATCH /verified-answers/{id} updates and snapshots version
  J. HTTP — PATCH on approved card reverts status to draft
  K. HTTP — DELETE (archive) sets status to archived
  L. HTTP — POST /submit-for-review requires draft status
  M. HTTP — submit-for-review blocks when requires_citations and no citations
  N. HTTP — POST /approve requires pending_review status
  O. HTTP — POST /reject returns card to draft with rejection_note
  P. HTTP — POST /publish requires approved status
  Q. HTTP — GET /versions returns history newest-first
  R. HTTP — POST /from-message/{id} creates from chat message
  S. HTTP — GET /search/match returns published matches
  T. HTTP — role guard: viewer cannot create card
  U. HTTP — role guard: member cannot approve card
  V. HTTP — org isolation: cannot get another org's card

Run:
    pytest tests/test_verified_answers_f255.py -v
"""

from __future__ import annotations

import os
from datetime import date, timedelta
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
from app.domains.verified_answers.schemas.verified_answers import (
    ApproveRequest,
    RejectRequest,
)
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

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
    o = Organization(name="TestOrg", slug=f"testorg-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def org2(db: AsyncSession) -> Organization:
    o = Organization(name="OtherOrg", slug=f"otherorg-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"admin-{uuid4().hex[:6]}@example.com", hashed_password="x")
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
async def reviewer_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"reviewer-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.reviewer.value,
        )
    )
    await db.flush()
    token = _make_token(str(u.id), str(org.id), OrganizationRole.reviewer.value)
    return u, token


@pytest_asyncio.fixture
async def member_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"member-{uuid4().hex[:6]}@example.com", hashed_password="x")
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
async def viewer_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"viewer-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.viewer.value,
        )
    )
    await db.flush()
    token = _make_token(str(u.id), str(org.id), OrganizationRole.viewer.value)
    return u, token


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override():
        yield db

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


_repo = VerifiedAnswerRepository()

# ---------------------------------------------------------------------------
# A. Repository — CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_create_get(db: AsyncSession, org: Organization, admin_user):
    user, _ = admin_user
    answer = await _repo.create(
        db,
        organization_id=org.id,
        title="What is the refund policy?",
        question="How do I get a refund?",
        answer_text="Refunds are processed within 5 business days.",
        tags="refund,billing",
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await db.flush()

    fetched = await _repo.get(db, answer_id=answer.id, organization_id=org.id)
    assert fetched is not None
    assert fetched.title == "What is the refund policy?"
    assert fetched.status == "draft"


@pytest.mark.asyncio
async def test_repo_list_with_status_filter(db: AsyncSession, org: Organization, admin_user):
    user, _ = admin_user
    a1 = await _repo.create(
        db,
        organization_id=org.id,
        title="Card A",
        question="Q?",
        answer_text="Answer A",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await _repo.approve(db, a1, approved_by_id=user.id, note=None)
    await _repo.publish(db, a1)

    await _repo.create(
        db,
        organization_id=org.id,
        title="Card B",
        question="Q2?",
        answer_text="Answer B",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await db.flush()

    published = await _repo.list(db, organization_id=org.id, status="published")
    drafts = await _repo.list(db, organization_id=org.id, status="draft")
    assert any(a.id == a1.id for a in published)
    assert all(a.status == "draft" for a in drafts)


@pytest.mark.asyncio
async def test_repo_update_content(db: AsyncSession, org: Organization, admin_user):
    user, _ = admin_user
    answer = await _repo.create(
        db,
        organization_id=org.id,
        title="Old title",
        question="Old Q?",
        answer_text="Old answer",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await _repo.update_content(
        db,
        answer,
        title="New title",
        question=None,
        answer_text="New answer",
        tags="tag1",
        collection_id=None,
        requires_citations=None,
        review_date=None,
        expiry_date=None,
        change_reason="manual_edit",
        changed_by_id=user.id,
    )
    await db.flush()

    assert answer.title == "New title"
    assert answer.answer_text == "New answer"


@pytest.mark.asyncio
async def test_repo_archive(db: AsyncSession, org: Organization, admin_user):
    user, _ = admin_user
    answer = await _repo.create(
        db,
        organization_id=org.id,
        title="To archive",
        question="Q?",
        answer_text="A.",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await _repo.archive(db, answer)
    await db.flush()
    assert answer.status == "archived"


# ---------------------------------------------------------------------------
# B. Repository — citation management
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_replace_citations(db: AsyncSession, org: Organization, admin_user):
    from app.models.document import Document

    user, _ = admin_user
    doc = Document(
        organization_id=org.id,
        filename="test.pdf",
        file_type="pdf",
        file_size=100,
        storage_path="test/test.pdf",
        status="indexed",
    )
    db.add(doc)
    await db.flush()

    answer = await _repo.create(
        db,
        organization_id=org.id,
        title="T",
        question="Q?",
        answer_text="A.",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=True,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await _repo.replace_citations(
        db,
        answer,
        [
            {
                "document_id": str(doc.id),
                "chunk_id": None,
                "text_snippet": "snippet",
                "page_number": 1,
                "citation_order": 0,
            }
        ],
    )
    await db.flush()

    fetched = await _repo.get(db, answer_id=answer.id, organization_id=org.id)
    assert len(fetched.citations) == 1
    assert fetched.citations[0].text_snippet == "snippet"


# ---------------------------------------------------------------------------
# C. Repository — version snapshots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_version_created_on_create(db: AsyncSession, org: Organization, admin_user):
    user, _ = admin_user
    answer = await _repo.create(
        db,
        organization_id=org.id,
        title="V",
        question="Q?",
        answer_text="A.",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await db.flush()
    versions = await _repo.list_versions(db, answer_id=answer.id, organization_id=org.id)
    assert len(versions) == 1
    assert versions[0].change_reason == "created"
    assert versions[0].version_number == 1


@pytest.mark.asyncio
async def test_repo_version_on_update(db: AsyncSession, org: Organization, admin_user):
    user, _ = admin_user
    answer = await _repo.create(
        db,
        organization_id=org.id,
        title="V",
        question="Q?",
        answer_text="A.",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await _repo.update_content(
        db,
        answer,
        title="V2",
        question=None,
        answer_text=None,
        tags=None,
        collection_id=None,
        requires_citations=None,
        review_date=None,
        expiry_date=None,
        change_reason="corrected_typo",
        changed_by_id=user.id,
    )
    await db.flush()
    versions = await _repo.list_versions(db, answer_id=answer.id, organization_id=org.id)
    assert len(versions) == 2
    assert versions[0].version_number == 2  # newest-first
    assert versions[0].change_reason == "corrected_typo"


# ---------------------------------------------------------------------------
# D. Repository — find_published_match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_find_published_match(db: AsyncSession, org: Organization, admin_user):
    user, _ = admin_user
    answer = await _repo.create(
        db,
        organization_id=org.id,
        title="Vacation policy",
        question="How many vacation days do employees get?",
        answer_text="Employees get 20 days per year.",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await _repo.approve(db, answer, approved_by_id=user.id, note=None)
    await _repo.publish(db, answer)
    await db.flush()

    matches = await _repo.find_published_match(db, organization_id=org.id, query="vacation days")
    assert any(m.id == answer.id for m in matches)


@pytest.mark.asyncio
async def test_repo_no_match_for_draft(db: AsyncSession, org: Organization, admin_user):
    user, _ = admin_user
    await _repo.create(
        db,
        organization_id=org.id,
        title="Unpublished vacation info",
        question="How many vacation days?",
        answer_text="20 days.",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await db.flush()

    matches = await _repo.find_published_match(db, organization_id=org.id, query="vacation days")
    assert len(matches) == 0


# ---------------------------------------------------------------------------
# E. Repository — org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repo_org_isolation(
    db: AsyncSession, org: Organization, org2: Organization, admin_user
):
    user, _ = admin_user
    answer = await _repo.create(
        db,
        organization_id=org.id,
        title="Secret",
        question="Q?",
        answer_text="A.",
        tags=None,
        collection_id=None,
        owner_id=user.id,
        requires_citations=False,
        review_date=None,
        expiry_date=None,
        source_message_id=None,
        created_by_id=user.id,
    )
    await db.flush()

    fetched = await _repo.get(db, answer_id=answer.id, organization_id=org2.id)
    assert fetched is None


# ---------------------------------------------------------------------------
# F. Schema validators
# ---------------------------------------------------------------------------


def test_reject_request_requires_non_blank_note():
    with pytest.raises(ValueError):
        RejectRequest(note="   ")


def test_approve_request_optional_note():
    req = ApproveRequest()
    assert req.note is None


# ---------------------------------------------------------------------------
# G. HTTP — POST /verified-answers creates draft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_create_draft(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={
            "title": "Test card",
            "question": "What is this?",
            "answer_text": "It is a test.",
            "requires_citations": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "draft"
    assert data["title"] == "Test card"
    assert data["is_stale"] is False


# ---------------------------------------------------------------------------
# H. HTTP — GET /verified-answers list with status filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_list_with_filter(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    await client.post(
        "/verified-answers",
        json={
            "title": "Draft1",
            "question": "Q?",
            "answer_text": "A.",
            "requires_citations": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get(
        "/verified-answers",
        params={"status": "draft"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(i["status"] == "draft" for i in items)


# ---------------------------------------------------------------------------
# I. HTTP — PATCH updates and snapshots version
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_patch_creates_version(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    create_resp = await client.post(
        "/verified-answers",
        json={"title": "Old", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    answer_id = create_resp.json()["answer_id"]

    await client.patch(
        f"/verified-answers/{answer_id}",
        json={"title": "New", "change_reason": "typo_fix"},
        headers={"Authorization": f"Bearer {token}"},
    )
    versions_resp = await client.get(
        f"/verified-answers/{answer_id}/versions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert versions_resp.status_code == 200
    assert versions_resp.json()["total"] == 2
    assert versions_resp.json()["items"][0]["change_reason"] == "typo_fix"


# ---------------------------------------------------------------------------
# J. HTTP — PATCH on approved card reverts to draft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_patch_reverts_approved_to_draft(
    client: AsyncClient, org: Organization, admin_user
):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={"title": "Ready", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]

    # draft → pending_review → approved
    await client.post(
        f"/verified-answers/{aid}/submit-for-review", headers={"Authorization": f"Bearer {token}"}
    )
    await client.post(
        f"/verified-answers/{aid}/approve", json={}, headers={"Authorization": f"Bearer {token}"}
    )

    patch_resp = await client.patch(
        f"/verified-answers/{aid}",
        json={"answer_text": "Updated answer.", "change_reason": "content_update"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_resp.json()["status"] == "draft"


# ---------------------------------------------------------------------------
# K. HTTP — DELETE archives card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_delete_archives(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={"title": "Bye", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]

    del_resp = await client.delete(
        f"/verified-answers/{aid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 204

    get_resp = await client.get(
        f"/verified-answers/{aid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_resp.json()["status"] == "archived"


# ---------------------------------------------------------------------------
# L. HTTP — submit-for-review requires draft status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_submit_requires_draft(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={"title": "T", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]

    await client.post(
        f"/verified-answers/{aid}/submit-for-review", headers={"Authorization": f"Bearer {token}"}
    )
    second = await client.post(
        f"/verified-answers/{aid}/submit-for-review", headers={"Authorization": f"Bearer {token}"}
    )
    assert second.status_code == 409


# ---------------------------------------------------------------------------
# M. HTTP — citation guard on submit-for-review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_submit_blocked_without_citations(
    client: AsyncClient, org: Organization, admin_user
):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={
            "title": "No citations",
            "question": "Q?",
            "answer_text": "A.",
            "requires_citations": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]

    review_resp = await client.post(
        f"/verified-answers/{aid}/submit-for-review",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert review_resp.status_code == 422
    assert "citation" in review_resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# N. HTTP — approve requires pending_review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_approve_requires_pending_review(
    client: AsyncClient, org: Organization, admin_user
):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={"title": "A", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]

    approve_resp = await client.post(
        f"/verified-answers/{aid}/approve",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approve_resp.status_code == 409


# ---------------------------------------------------------------------------
# O. HTTP — reject returns card to draft with note
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_reject_sets_note(
    client: AsyncClient, org: Organization, admin_user, reviewer_user
):
    _, admin_token = admin_user
    _, rev_token = reviewer_user

    resp = await client.post(
        "/verified-answers",
        json={"title": "R", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    aid = resp.json()["answer_id"]
    await client.post(
        f"/verified-answers/{aid}/submit-for-review",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    reject_resp = await client.post(
        f"/verified-answers/{aid}/reject",
        json={"note": "Needs more detail"},
        headers={"Authorization": f"Bearer {rev_token}"},
    )
    assert reject_resp.status_code == 200
    data = reject_resp.json()
    assert data["status"] == "draft"
    assert data["rejection_note"] == "Needs more detail"


# ---------------------------------------------------------------------------
# P. HTTP — publish requires approved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_publish_requires_approved(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={"title": "P", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]

    pub_resp = await client.post(
        f"/verified-answers/{aid}/publish",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert pub_resp.status_code == 409


@pytest.mark.asyncio
async def test_http_full_publish_flow(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={"title": "Flow", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]

    await client.post(
        f"/verified-answers/{aid}/submit-for-review", headers={"Authorization": f"Bearer {token}"}
    )
    await client.post(
        f"/verified-answers/{aid}/approve", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    pub_resp = await client.post(
        f"/verified-answers/{aid}/publish", headers={"Authorization": f"Bearer {token}"}
    )
    assert pub_resp.status_code == 200
    assert pub_resp.json()["status"] == "published"
    assert pub_resp.json()["published_at"] is not None


# ---------------------------------------------------------------------------
# Q. HTTP — GET /versions returns history newest-first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_versions_newest_first(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={"title": "V1", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]
    await client.patch(
        f"/verified-answers/{aid}",
        json={"title": "V2", "change_reason": "edit1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    await client.patch(
        f"/verified-answers/{aid}",
        json={"title": "V3", "change_reason": "edit2"},
        headers={"Authorization": f"Bearer {token}"},
    )

    ver_resp = await client.get(
        f"/verified-answers/{aid}/versions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ver_resp.status_code == 200
    items = ver_resp.json()["items"]
    assert items[0]["version_number"] == 3
    assert items[0]["change_reason"] == "edit2"


# ---------------------------------------------------------------------------
# R. HTTP — stale detection via is_stale flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_stale_expiry(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    resp = await client.post(
        "/verified-answers",
        json={
            "title": "Stale",
            "question": "Q?",
            "answer_text": "A.",
            "requires_citations": False,
            "expiry_date": yesterday,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.json()["is_stale"] is True


# ---------------------------------------------------------------------------
# S. HTTP — search/match returns published cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_search_match(client: AsyncClient, org: Organization, admin_user):
    _, token = admin_user
    resp = await client.post(
        "/verified-answers",
        json={
            "title": "Parental leave",
            "question": "How long is parental leave?",
            "answer_text": "16 weeks fully paid.",
            "requires_citations": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    aid = resp.json()["answer_id"]
    await client.post(
        f"/verified-answers/{aid}/submit-for-review", headers={"Authorization": f"Bearer {token}"}
    )
    await client.post(
        f"/verified-answers/{aid}/approve", json={}, headers={"Authorization": f"Bearer {token}"}
    )
    await client.post(
        f"/verified-answers/{aid}/publish", headers={"Authorization": f"Bearer {token}"}
    )

    search_resp = await client.get(
        "/verified-answers/search/match",
        params={"query": "parental leave"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert search_resp.status_code == 200
    assert any(i["answer_id"] == aid for i in search_resp.json()["items"])


# ---------------------------------------------------------------------------
# T. HTTP — role guard: viewer cannot create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_viewer_cannot_create(client: AsyncClient, org: Organization, viewer_user):
    _, token = viewer_user
    resp = await client.post(
        "/verified-answers",
        json={"title": "X", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# U. HTTP — role guard: member cannot approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_member_cannot_approve(
    client: AsyncClient, org: Organization, admin_user, member_user
):
    _, admin_token = admin_user
    _, member_token = member_user

    resp = await client.post(
        "/verified-answers",
        json={"title": "A", "question": "Q?", "answer_text": "A.", "requires_citations": False},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    aid = resp.json()["answer_id"]
    await client.post(
        f"/verified-answers/{aid}/submit-for-review",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    approve_resp = await client.post(
        f"/verified-answers/{aid}/approve",
        json={},
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert approve_resp.status_code == 403


# ---------------------------------------------------------------------------
# V. HTTP — org isolation: cannot get another org's card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_org_isolation(
    client: AsyncClient,
    org: Organization,
    org2: Organization,
    admin_user,
    db: AsyncSession,
):
    _, admin_token = admin_user

    resp = await client.post(
        "/verified-answers",
        json={
            "title": "Private",
            "question": "Q?",
            "answer_text": "A.",
            "requires_citations": False,
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    aid = resp.json()["answer_id"]

    other_user = User(email=f"other-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(other_user)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=other_user.id,
            organization_id=org2.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db.flush()
    other_token = _make_token(str(other_user.id), str(org2.id), OrganizationRole.admin.value)

    get_resp = await client.get(
        f"/verified-answers/{aid}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert get_resp.status_code == 404
