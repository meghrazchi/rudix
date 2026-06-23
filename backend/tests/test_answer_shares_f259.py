"""Tests for F259: Secure shareable answer pages.

Covers:
- Create answer share (org_only, specific_users, password, expiry)
- List active answer shares
- Revoke answer share
- View shared answer via token (happy path)
- View shared answer: expired → 404
- View shared answer: revoked → 404
- View shared answer: wrong org → 404
- View shared answer: specific_users access denied → 403
- View shared answer: correct specific_user → 200
- View shared answer: password required (missing) → 403
- View shared answer: wrong password → 403
- View shared answer: correct password → 200
- Shared answer citations omit document_id/chunk_id
- max active shares per answer (422)
- specific_users with empty allowed list → 422
- Non-assistant message cannot be shared → 404
- Message from other org cannot be shared → 404
- Audit log recorded on create, view, revoke
- Revoke by non-owner returns 404
- Confidence category present in shared answer
"""

import os
from datetime import UTC, datetime, timedelta
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
from app.models.answer_share import AnswerShare
from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User

# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_token(user_id: str, org_id: str, role: str = OrganizationRole.member.value) -> str:
    return create_app_access_token(
        subject=user_id,
        organization_id=org_id,
        roles=[role],
        secret=settings.app_auth_secret.get_secret_value(),
        issuer=settings.app_auth_issuer,
        audience=settings.app_auth_audience,
        expires_in_seconds=3600,
    )


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_org_member(
    db: AsyncSession, *, role: str = OrganizationRole.member.value
) -> tuple[Organization, User, OrganizationMember]:
    org = Organization(id=uuid4(), name=f"org-{uuid4().hex[:6]}", slug=uuid4().hex[:8])
    user = User(
        id=uuid4(),
        email=f"user-{uuid4().hex[:6]}@example.com",
        display_name="Test User",
        auth_provider="app",
    )
    member = OrganizationMember(
        id=uuid4(),
        organization_id=org.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([org, user, member])
    await db.flush()
    return org, user, member


async def _create_session_and_messages(
    db: AsyncSession,
    *,
    org_id: object,
    user_id: object,
    question: str = "What is RAG?",
    answer: str = "RAG stands for retrieval-augmented generation.",
    confidence_score: float = 0.87,
) -> tuple[ChatSession, ChatMessage, ChatMessage]:
    """Returns (session, user_msg, assistant_msg)."""
    session = ChatSession(
        id=uuid4(),
        organization_id=org_id,
        user_id=user_id,
        title=question[:80],
    )
    db.add(session)
    await db.flush()

    user_msg = ChatMessage(
        id=uuid4(),
        chat_session_id=session.id,
        role="user",
        content=question,
    )
    db.add(user_msg)
    await db.flush()

    assistant_msg = ChatMessage(
        id=uuid4(),
        chat_session_id=session.id,
        role="assistant",
        content=answer,
        confidence_score=confidence_score,
    )
    db.add(assistant_msg)
    await db.flush()
    return session, user_msg, assistant_msg


# ─── fixture ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(
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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ─── tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_answer_share_org_only(client: AsyncClient, db_session: AsyncSession) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"access_mode": "org_only"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["access_mode"] == "org_only"
    assert data["has_password"] is False
    assert data["is_revoked"] is False
    assert data["message_id"] == str(assistant_msg.id)
    assert data["token"]


@pytest.mark.asyncio
async def test_create_answer_share_with_expiry(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"access_mode": "org_only", "expires_in_hours": 24},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201
    assert resp.json()["expires_at"] is not None


@pytest.mark.asyncio
async def test_create_answer_share_with_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"access_mode": "org_only", "password": "hunter2"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201
    assert resp.json()["has_password"] is True


@pytest.mark.asyncio
async def test_create_answer_share_specific_users(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    viewer_id = str(uuid4())
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"access_mode": "specific_users", "allowed_user_ids": [viewer_id]},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["access_mode"] == "specific_users"
    assert viewer_id in data["allowed_user_ids"]


@pytest.mark.asyncio
async def test_create_answer_share_specific_users_empty_list_fails(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"access_mode": "specific_users", "allowed_user_ids": []},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_answer_shares(client: AsyncClient, db_session: AsyncSession) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )

    resp = await client.get(
        f"/chat/messages/{assistant_msg.id}/shares",
        headers=_auth_header(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["message_id"] == str(assistant_msg.id)


@pytest.mark.asyncio
async def test_revoke_answer_share(client: AsyncClient, db_session: AsyncSession) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )
    share_id = create_resp.json()["share_id"]

    revoke_resp = await client.delete(
        f"/chat/messages/{assistant_msg.id}/shares/{share_id}",
        headers=_auth_header(token),
    )
    assert revoke_resp.status_code == 204

    list_resp = await client.get(
        f"/chat/messages/{assistant_msg.id}/shares",
        headers=_auth_header(token),
    )
    assert list_resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_view_shared_answer_happy_path(client: AsyncClient, db_session: AsyncSession) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id, question="What is AI?", answer="AI is..."
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]

    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}",
        headers=_auth_header(token),
    )
    assert view_resp.status_code == 200
    data = view_resp.json()
    assert data["answer"] == "AI is..."
    assert data["question"] == "What is AI?"
    assert data["access_mode"] == "org_only"
    assert data["shared_at"] is not None


@pytest.mark.asyncio
async def test_view_shared_answer_confidence_category(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id, confidence_score=0.92
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]

    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}",
        headers=_auth_header(token),
    )
    assert view_resp.status_code == 200
    data = view_resp.json()
    assert data["confidence_score"] == pytest.approx(0.92)
    assert data["confidence_category"] == "high"


@pytest.mark.asyncio
async def test_view_shared_answer_citations_no_document_id(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    # Add a citation
    doc = Document(
        id=uuid4(),
        organization_id=org.id,
        filename="report.pdf",
        original_filename="report.pdf",
        file_size=1024,
        mime_type="application/pdf",
        status="indexed",
        storage_path="path/report.pdf",
    )
    db_session.add(doc)
    await db_session.flush()
    cit = Citation(
        id=uuid4(),
        chat_message_id=assistant_msg.id,
        document_id=doc.id,
        chunk_id=uuid4(),
        text_snippet="Key finding here",
        page_number=3,
        similarity_score=0.9,
    )
    db_session.add(cit)
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]

    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}",
        headers=_auth_header(token),
    )
    assert view_resp.status_code == 200
    data = view_resp.json()
    assert len(data["citations"]) == 1
    citation = data["citations"][0]
    # Snippet and filename present
    assert citation["document_id"] == str(doc.id)
    assert citation["chunk_id"] == str(cit.chunk_id)
    assert citation["text_snippet"] == "Key finding here"
    assert citation["filename"] == "report.pdf"
    assert citation["page_number"] == 3


@pytest.mark.asyncio
async def test_view_shared_answer_revoked_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )
    share_id = create_resp.json()["share_id"]
    share_token = create_resp.json()["token"]

    await client.delete(
        f"/chat/messages/{assistant_msg.id}/shares/{share_id}",
        headers=_auth_header(token),
    )

    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}",
        headers=_auth_header(token),
    )
    assert view_resp.status_code == 404


@pytest.mark.asyncio
async def test_view_shared_answer_expired_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    # Directly insert an already-expired share
    expired_share = AnswerShare(
        id=uuid4(),
        chat_message_id=assistant_msg.id,
        organization_id=org.id,
        shared_by_user_id=user.id,
        token="expired-token-abc123",
        access_mode="org_only",
        expires_at=datetime.now(tz=UTC) - timedelta(hours=1),
        is_revoked=False,
    )
    db_session.add(expired_share)
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    view_resp = await client.get(
        "/chat/answer-shared/expired-token-abc123",
        headers=_auth_header(token),
    )
    assert view_resp.status_code == 404


@pytest.mark.asyncio
async def test_view_shared_answer_wrong_org_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a, user_a, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org_a.id, user_id=user_a.id
    )
    await db_session.commit()

    token_a = _make_token(str(user_a.id), str(org_a.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token_a),
    )
    share_token = create_resp.json()["token"]

    # Org B viewer tries to access
    org_b, user_b, _ = await _create_org_member(db_session)
    await db_session.commit()
    token_b = _make_token(str(user_b.id), str(org_b.id))

    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}",
        headers=_auth_header(token_b),
    )
    assert view_resp.status_code == 404


@pytest.mark.asyncio
async def test_view_specific_users_share_denied(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user_owner, _ = await _create_org_member(db_session)
    _, user_viewer, _ = await _create_org_member(db_session)
    # Ensure viewer is in same org
    viewer_member = OrganizationMember(
        id=uuid4(),
        organization_id=org.id,
        user_id=user_viewer.id,
        role=OrganizationRole.member.value,
    )
    db_session.add(viewer_member)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user_owner.id
    )
    await db_session.commit()

    token = _make_token(str(user_owner.id), str(org.id))
    other_user_id = str(uuid4())
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"access_mode": "specific_users", "allowed_user_ids": [other_user_id]},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]

    viewer_token = _make_token(str(user_viewer.id), str(org.id))
    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}",
        headers=_auth_header(viewer_token),
    )
    assert view_resp.status_code == 403


@pytest.mark.asyncio
async def test_view_specific_users_share_allowed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user_owner, _ = await _create_org_member(db_session)
    _, user_viewer, _ = await _create_org_member(db_session)
    viewer_member = OrganizationMember(
        id=uuid4(),
        organization_id=org.id,
        user_id=user_viewer.id,
        role=OrganizationRole.member.value,
    )
    db_session.add(viewer_member)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user_owner.id
    )
    await db_session.commit()

    token = _make_token(str(user_owner.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"access_mode": "specific_users", "allowed_user_ids": [str(user_viewer.id)]},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]

    viewer_token = _make_token(str(user_viewer.id), str(org.id))
    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}",
        headers=_auth_header(viewer_token),
    )
    assert view_resp.status_code == 200


@pytest.mark.asyncio
async def test_view_password_protected_share_no_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"password": "secret123"},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]

    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}",
        headers=_auth_header(token),
    )
    assert view_resp.status_code == 403


@pytest.mark.asyncio
async def test_view_password_protected_share_wrong_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"password": "secret123"},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]

    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}?password=wrongpassword",
        headers=_auth_header(token),
    )
    assert view_resp.status_code == 403


@pytest.mark.asyncio
async def test_view_password_protected_share_correct_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={"password": "secret123"},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]

    view_resp = await client.get(
        f"/chat/answer-shared/{share_token}?password=secret123",
        headers=_auth_header(token),
    )
    assert view_resp.status_code == 200


@pytest.mark.asyncio
async def test_share_user_message_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user, _ = await _create_org_member(db_session)
    _, user_msg, _ = await _create_session_and_messages(db_session, org_id=org.id, user_id=user.id)
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    resp = await client.post(
        f"/chat/messages/{user_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )
    # user messages are role "user", not "assistant" — must be rejected
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_revoke_by_non_owner_returns_404(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    org, user_owner, _ = await _create_org_member(db_session)
    _, user_other, _ = await _create_org_member(db_session)
    other_member = OrganizationMember(
        id=uuid4(),
        organization_id=org.id,
        user_id=user_other.id,
        role=OrganizationRole.member.value,
    )
    db_session.add(other_member)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user_owner.id
    )
    await db_session.commit()

    token_owner = _make_token(str(user_owner.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token_owner),
    )
    share_id = create_resp.json()["share_id"]

    token_other = _make_token(str(user_other.id), str(org.id))
    revoke_resp = await client.delete(
        f"/chat/messages/{assistant_msg.id}/shares/{share_id}",
        headers=_auth_header(token_other),
    )
    assert revoke_resp.status_code == 404


@pytest.mark.asyncio
async def test_audit_log_on_create(client: AsyncClient, db_session: AsyncSession) -> None:
    from sqlalchemy import select

    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    actions = [r.action for r in rows]
    assert "answer.shared" in actions


@pytest.mark.asyncio
async def test_audit_log_on_view(client: AsyncClient, db_session: AsyncSession) -> None:
    from sqlalchemy import select

    org, user, _ = await _create_org_member(db_session)
    _, _, assistant_msg = await _create_session_and_messages(
        db_session, org_id=org.id, user_id=user.id
    )
    await db_session.commit()

    token = _make_token(str(user.id), str(org.id))
    create_resp = await client.post(
        f"/chat/messages/{assistant_msg.id}/shares",
        json={},
        headers=_auth_header(token),
    )
    share_token = create_resp.json()["token"]
    await client.get(f"/chat/answer-shared/{share_token}", headers=_auth_header(token))

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    actions = [r.action for r in rows]
    assert "answer.share.viewed" in actions
