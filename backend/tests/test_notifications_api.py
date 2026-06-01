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
from app.domains.notifications.repositories.notifications import NotificationRepository
from app.main import app
from app.models.enums import NotificationEventType, NotificationSeverity, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_notification_repo = NotificationRepository()


@pytest_asyncio.fixture
async def notifications_client(
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
    org = Organization(name="Notif Org", slug=f"notif-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"notif-user-{uuid4().hex[:8]}",
        email=f"notif-{uuid4().hex[:8]}@example.com",
        display_name="Notification User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value)
    )
    await db_session.commit()
    return user, org


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


async def _seed_notification(
    db_session: AsyncSession,
    *,
    user: User,
    org: Organization,
    event_type: NotificationEventType = NotificationEventType.upload_indexed,
    severity: NotificationSeverity = NotificationSeverity.info,
    title: str = "Test notification",
    is_read: bool = False,
):
    n = await _notification_repo.create_notification(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=event_type,
        severity=severity,
        title=title,
        message="Test message",
        href="/documents",
        source_id=str(uuid4()),
    )
    if is_read:
        await _notification_repo.mark_read(
            db_session,
            notification_id=n.id,
            organization_id=org.id,
            user_id=user.id,
            is_read=True,
        )
    await db_session.commit()
    return n


class TestListNotifications:
    async def test_returns_empty_for_new_user(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.get(
            "/api/v1/notifications", headers=_headers(token=token, organization_id=str(org.id))
        )
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0
        assert body["unread_count"] == 0

    async def test_returns_notifications_newest_first(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        n1 = await _seed_notification(db_session, user=user, org=org, title="First")
        n2 = await _seed_notification(db_session, user=user, org=org, title="Second")

        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.get(
            "/api/v1/notifications", headers=_headers(token=token, organization_id=str(org.id))
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["unread_count"] == 2
        assert body["items"][0]["notification_id"] == str(n2.id)
        assert body["items"][1]["notification_id"] == str(n1.id)

    async def test_unread_count_excludes_read_notifications(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        await _seed_notification(db_session, user=user, org=org, is_read=True)
        await _seed_notification(db_session, user=user, org=org, is_read=False)

        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.get(
            "/api/v1/notifications", headers=_headers(token=token, organization_id=str(org.id))
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert body["unread_count"] == 1

    async def test_org_scoped_does_not_expose_other_org_notifications(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_a, org_a = await _seed_principal(db_session)
        user_b, org_b = await _seed_principal(db_session)
        await _seed_notification(db_session, user=user_b, org=org_b, title="Org B notification")

        token = create_app_access_token(
            subject=str(user_a.id), organization_id=str(org_a.id), email=user_a.email
        )
        response = await notifications_client.get(
            "/api/v1/notifications", headers=_headers(token=token, organization_id=str(org_a.id))
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_pagination(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        for i in range(5):
            await _seed_notification(db_session, user=user, org=org, title=f"Notif {i}")

        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.get(
            "/api/v1/notifications?limit=2&offset=0",
            headers=_headers(token=token, organization_id=str(org.id)),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["limit"] == 2
        assert body["offset"] == 0


class TestUnreadCount:
    async def test_returns_correct_unread_count(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        await _seed_notification(db_session, user=user, org=org, is_read=False)
        await _seed_notification(db_session, user=user, org=org, is_read=False)
        await _seed_notification(db_session, user=user, org=org, is_read=True)

        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.get(
            "/api/v1/notifications/unread-count",
            headers=_headers(token=token, organization_id=str(org.id)),
        )
        assert response.status_code == 200
        assert response.json()["unread_count"] == 2


class TestMarkRead:
    async def test_mark_read_updates_notification(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        n = await _seed_notification(db_session, user=user, org=org)
        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.patch(
            f"/api/v1/notifications/{n.id}/read",
            headers=_headers(token=token, organization_id=str(org.id)),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["is_read"] is True
        assert body["notification_id"] == str(n.id)

    async def test_mark_unread_updates_notification(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        n = await _seed_notification(db_session, user=user, org=org, is_read=True)
        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.patch(
            f"/api/v1/notifications/{n.id}/unread",
            headers=_headers(token=token, organization_id=str(org.id)),
        )
        assert response.status_code == 200
        assert response.json()["is_read"] is False

    async def test_mark_read_returns_404_for_wrong_user(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_a, org_a = await _seed_principal(db_session)
        user_b, org_b = await _seed_principal(db_session)
        n = await _seed_notification(db_session, user=user_b, org=org_b)

        token = create_app_access_token(
            subject=str(user_a.id), organization_id=str(org_a.id), email=user_a.email
        )
        response = await notifications_client.patch(
            f"/api/v1/notifications/{n.id}/read",
            headers=_headers(token=token, organization_id=str(org_a.id)),
        )
        assert response.status_code == 404

    async def test_mark_read_returns_422_for_invalid_id(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.patch(
            "/api/v1/notifications/not-a-uuid/read",
            headers=_headers(token=token, organization_id=str(org.id)),
        )
        assert response.status_code == 422


class TestMarkAllRead:
    async def test_marks_all_unread_notifications(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_principal(db_session)
        for _ in range(3):
            await _seed_notification(db_session, user=user, org=org)

        token = create_app_access_token(
            subject=str(user.id), organization_id=str(org.id), email=user.email
        )
        response = await notifications_client.post(
            "/api/v1/notifications/mark-all-read",
            headers=_headers(token=token, organization_id=str(org.id)),
        )
        assert response.status_code == 200
        assert response.json()["marked_count"] == 3

        count_response = await notifications_client.get(
            "/api/v1/notifications/unread-count",
            headers=_headers(token=token, organization_id=str(org.id)),
        )
        assert count_response.json()["unread_count"] == 0

    async def test_mark_all_read_only_affects_current_user(
        self, notifications_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_a, org_a = await _seed_principal(db_session)
        user_b, org_b = await _seed_principal(db_session)
        await _seed_notification(db_session, user=user_b, org=org_b)

        token = create_app_access_token(
            subject=str(user_a.id), organization_id=str(org_a.id), email=user_a.email
        )
        response = await notifications_client.post(
            "/api/v1/notifications/mark-all-read",
            headers=_headers(token=token, organization_id=str(org_a.id)),
        )
        assert response.status_code == 200
        assert response.json()["marked_count"] == 0

    async def test_requires_authentication(self, notifications_client: AsyncClient) -> None:
        response = await notifications_client.get("/api/v1/notifications")
        assert response.status_code == 401
