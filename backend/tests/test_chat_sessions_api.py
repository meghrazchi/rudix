import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
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
from app.domains.chat.repositories.chat import ChatRepository
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def chat_sessions_client(
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
) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Chat Primary", slug=f"chat-primary-{uuid4().hex[:8]}")
    secondary_org = Organization(name="Chat Secondary", slug=f"chat-secondary-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, secondary_org])
    await db_session.flush()

    user = User(
        organization_id=primary_org.id,
        external_auth_id=f"chat-user-{uuid4().hex[:8]}",
        email=f"chat-{uuid4().hex[:8]}@example.com",
        display_name="Chat API User",
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
    role: OrganizationRole = OrganizationRole.member,
) -> User:
    user = User(
        organization_id=organization.id,
        external_auth_id=f"chat-org-user-{uuid4().hex[:8]}",
        email=f"chat-org-{uuid4().hex[:8]}@example.com",
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


@pytest.mark.asyncio
async def test_create_chat_session_persists_record(
    chat_sessions_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await chat_sessions_client.post(
        "/api/v1/chat/sessions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={"title": "Project Intake"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "Project Intake"
    assert payload["message_count"] == 0

    repository = ChatRepository()
    sessions = await repository.list_chat_sessions(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
    )
    assert len(sessions) == 1
    assert str(sessions[0].id) == payload["session_id"]
    assert sessions[0].title == "Project Intake"


@pytest.mark.asyncio
async def test_create_chat_session_validates_title(
    chat_sessions_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, _ = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    blank_title_response = await chat_sessions_client.post(
        "/api/v1/chat/sessions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={"title": "   "},
    )
    assert blank_title_response.status_code == 422

    long_title_response = await chat_sessions_client.post(
        "/api/v1/chat/sessions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        json={"title": "x" * 256},
    )
    assert long_title_response.status_code == 422


@pytest.mark.asyncio
async def test_list_chat_sessions_scoped_to_user_and_org(
    chat_sessions_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = ChatRepository()
    user, organization, other_organization = await _seed_principal(db_session)
    other_user_same_org = await _seed_user_for_org(db_session, organization=organization)
    other_user_other_org = await _seed_user_for_org(db_session, organization=other_organization)

    own_session_old = await repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        title="Own Session Old",
    )
    own_session_new = await repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        title="Own Session New",
    )
    _ = await repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=other_user_same_org.id,
        title="Other User Session",
    )
    _ = await repository.create_chat_session(
        db_session,
        organization_id=other_organization.id,
        user_id=other_user_other_org.id,
        title="Other Org Session",
    )
    await repository.create_chat_message(
        db_session,
        chat_session_id=own_session_new.id,
        content="hello",
    )
    await repository.create_chat_message(
        db_session,
        chat_session_id=own_session_new.id,
        content="world",
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await chat_sessions_client.get(
        "/api/v1/chat/sessions",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert len(payload["items"]) == 2

    returned_ids = {item["session_id"] for item in payload["items"]}
    assert returned_ids == {str(own_session_old.id), str(own_session_new.id)}
    counts_by_id = {item["session_id"]: item["message_count"] for item in payload["items"]}
    assert counts_by_id[str(own_session_old.id)] == 0
    assert counts_by_id[str(own_session_new.id)] == 2


@pytest.mark.asyncio
async def test_get_chat_session_rejects_inaccessible_sessions(
    chat_sessions_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = ChatRepository()
    user, organization, other_organization = await _seed_principal(db_session)
    other_user_same_org = await _seed_user_for_org(db_session, organization=organization)
    other_user_other_org = await _seed_user_for_org(db_session, organization=other_organization)

    own_session = await repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        title="Accessible Session",
    )
    same_org_other_user_session = await repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=other_user_same_org.id,
        title="Blocked Session",
    )
    other_org_session = await repository.create_chat_session(
        db_session,
        organization_id=other_organization.id,
        user_id=other_user_other_org.id,
        title="Blocked Org Session",
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    own_response = await chat_sessions_client.get(
        f"/api/v1/chat/sessions/{own_session.id}",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert own_response.status_code == 200
    assert own_response.json()["session_id"] == str(own_session.id)

    same_org_response = await chat_sessions_client.get(
        f"/api/v1/chat/sessions/{same_org_other_user_session.id}",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert same_org_response.status_code == 404
    assert same_org_response.json()["detail"] == "Chat session not found"

    other_org_response = await chat_sessions_client.get(
        f"/api/v1/chat/sessions/{other_org_session.id}",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert other_org_response.status_code == 404
    assert other_org_response.json()["detail"] == "Chat session not found"

    invalid_id_response = await chat_sessions_client.get(
        "/api/v1/chat/sessions/not-a-uuid",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert invalid_id_response.status_code == 404
    assert invalid_id_response.json()["detail"] == "Chat session not found"


@pytest.mark.asyncio
async def test_list_chat_session_messages_returns_history_for_accessible_session(
    chat_sessions_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = ChatRepository()
    user, organization, _ = await _seed_principal(db_session)
    chat_session = await repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        title="History Session",
    )
    user_message = await repository.create_chat_message(
        db_session,
        chat_session_id=chat_session.id,
        role="user",
        content="What changed?",
    )
    assistant_message = await repository.create_chat_message(
        db_session,
        chat_session_id=chat_session.id,
        role="assistant",
        content="The policy was updated in May 2026.",
        confidence_score=0.81,
    )
    secondary_assistant_message = await repository.create_chat_message(
        db_session,
        chat_session_id=chat_session.id,
        role="assistant",
        content="Secondary note",
        confidence_score=0.55,
    )
    base_created_at = datetime.now(UTC)
    user_message.created_at = base_created_at
    assistant_message.created_at = base_created_at + timedelta(seconds=1)
    secondary_assistant_message.created_at = base_created_at + timedelta(seconds=2)
    await db_session.flush()
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await chat_sessions_client.get(
        f"/api/v1/chat/sessions/{chat_session.id}/messages",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
        params={"limit": 2, "offset": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["limit"] == 2
    assert payload["offset"] == 0
    assert len(payload["items"]) == 2
    assert payload["items"][0]["role"] == "user"
    assert payload["items"][0]["content"] == "What changed?"
    assert payload["items"][0]["confidence_category"] is None
    assert payload["items"][1]["message_id"] == str(assistant_message.id)
    assert payload["items"][1]["role"] == "assistant"
    assert payload["items"][1]["confidence_category"] == "high"


@pytest.mark.asyncio
async def test_list_chat_session_messages_rejects_inaccessible_sessions(
    chat_sessions_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = ChatRepository()
    user, organization, other_organization = await _seed_principal(db_session)
    other_user_same_org = await _seed_user_for_org(db_session, organization=organization)
    other_user_other_org = await _seed_user_for_org(db_session, organization=other_organization)

    same_org_other_user_session = await repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=other_user_same_org.id,
        title="Blocked Session",
    )
    other_org_session = await repository.create_chat_session(
        db_session,
        organization_id=other_organization.id,
        user_id=other_user_other_org.id,
        title="Blocked Org Session",
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    same_org_response = await chat_sessions_client.get(
        f"/api/v1/chat/sessions/{same_org_other_user_session.id}/messages",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert same_org_response.status_code == 404
    assert same_org_response.json()["detail"] == "Chat session not found"

    other_org_response = await chat_sessions_client.get(
        f"/api/v1/chat/sessions/{other_org_session.id}/messages",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert other_org_response.status_code == 404
    assert other_org_response.json()["detail"] == "Chat session not found"

    invalid_id_response = await chat_sessions_client.get(
        "/api/v1/chat/sessions/not-a-uuid/messages",
        headers=_auth_headers(token=token, organization_id=str(organization.id)),
    )
    assert invalid_id_response.status_code == 404
    assert invalid_id_response.json()["detail"] == "Chat session not found"
