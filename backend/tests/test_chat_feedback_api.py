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
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.chat.repositories.feedback import FeedbackRepository
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def feedback_client(
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
    role: OrganizationRole = OrganizationRole.member,
) -> tuple[User, Organization]:
    org = Organization(name="Feedback Org", slug=f"feedback-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"fb-user-{uuid4().hex[:8]}",
        email=f"fb-{uuid4().hex[:8]}@example.com",
        display_name="Feedback User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


async def _seed_assistant_message(
    db_session: AsyncSession, *, org: Organization, user: User
) -> tuple:
    repo = ChatRepository()
    session = await repo.create_chat_session(
        db_session, organization_id=org.id, user_id=user.id, title="Test"
    )
    msg = await repo.create_chat_message(
        db_session, chat_session_id=session.id, role="assistant", content="Test answer."
    )
    await db_session.commit()
    return session, msg


@pytest.mark.asyncio
async def test_submit_feedback_creates_record(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    _chat_session, msg = await _seed_assistant_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await feedback_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "up"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rating"] == "up"
    assert payload["reason"] is None
    assert payload["comment"] is None
    assert payload["message_id"] == str(msg.id)
    assert payload["user_id"] == str(user.id)

    repo = FeedbackRepository()
    saved = await repo.get_feedback(
        db_session, message_id=msg.id, user_id=user.id, organization_id=org.id
    )
    assert saved is not None
    assert saved.rating == "up"


@pytest.mark.asyncio
async def test_submit_feedback_with_reason_and_comment(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    _, msg = await _seed_assistant_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await feedback_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "down", "reason": "wrong_citation", "comment": "Citation 2 is wrong."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rating"] == "down"
    assert payload["reason"] == "wrong_citation"
    assert payload["comment"] == "Citation 2 is wrong."


@pytest.mark.asyncio
async def test_submit_feedback_updates_existing(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    _, msg = await _seed_assistant_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    await feedback_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "up"},
    )
    response = await feedback_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "down", "reason": "hallucination"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rating"] == "down"
    assert payload["reason"] == "hallucination"

    repo = FeedbackRepository()
    items = await repo.list_feedback_for_session(
        db_session, chat_session_id=msg.chat_session_id, organization_id=org.id, user_id=user.id
    )
    assert len(items) == 1
    assert items[0].rating == "down"


@pytest.mark.asyncio
async def test_submit_feedback_rejects_nonexistent_message(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await feedback_client.put(
        f"/api/v1/chat/messages/{uuid4()}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "up"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_submit_feedback_rejects_cross_org_message(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_principal(db_session)
    user_b, org_b = await _seed_principal(db_session)
    _, msg_b = await _seed_assistant_message(db_session, org=org_b, user=user_b)

    token_a = create_app_access_token(
        subject=user_a.external_auth_id,
        organization_id=str(org_a.id),
        expires_in_seconds=600,
    )

    response = await feedback_client.put(
        f"/api/v1/chat/messages/{msg_b.id}/feedback",
        headers=_headers(token=token_a, organization_id=str(org_a.id)),
        json={"rating": "up"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_submit_feedback_rejects_comment_too_long(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    _, msg = await _seed_assistant_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await feedback_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "down", "comment": "x" * 1001},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_delete_feedback_removes_record(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    _, msg = await _seed_assistant_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    await feedback_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "up"},
    )
    response = await feedback_client.delete(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 204

    repo = FeedbackRepository()
    saved = await repo.get_feedback(
        db_session, message_id=msg.id, user_id=user.id, organization_id=org.id
    )
    assert saved is None


@pytest.mark.asyncio
async def test_delete_feedback_returns_404_if_none_exists(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    _, msg = await _seed_assistant_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await feedback_client.delete(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_session_feedback_returns_user_feedback(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    chat_session, msg = await _seed_assistant_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    await feedback_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "down", "reason": "outdated_source"},
    )

    response = await feedback_client.get(
        f"/api/v1/chat/sessions/{chat_session.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["rating"] == "down"
    assert payload["items"][0]["reason"] == "outdated_source"
    assert payload["items"][0]["message_id"] == str(msg.id)


@pytest.mark.asyncio
async def test_list_session_feedback_scoped_to_user(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org = await _seed_principal(db_session)
    user_b = User(
        organization_id=org.id,
        external_auth_id=f"fb-user-b-{uuid4().hex[:8]}",
        email=f"fb-b-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user_b)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user_b.id, role=OrganizationRole.member.value
        )
    )
    await db_session.commit()

    chat_session, msg = await _seed_assistant_message(db_session, org=org, user=user_a)

    repo = FeedbackRepository()
    await repo.upsert_feedback(
        db_session,
        message_id=msg.id,
        user_id=user_b.id,
        organization_id=org.id,
        rating="up",
        reason=None,
        comment=None,
    )
    await db_session.commit()

    token_a = create_app_access_token(
        subject=user_a.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await feedback_client.get(
        f"/api/v1/chat/sessions/{chat_session.id}/feedback",
        headers=_headers(token=token_a, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0


@pytest.mark.asyncio
async def test_list_session_feedback_rejects_wrong_session(
    feedback_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await feedback_client.get(
        f"/api/v1/chat/sessions/{uuid4()}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 404
