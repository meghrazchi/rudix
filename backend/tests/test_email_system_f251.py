"""Tests for F251 transactional email system."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
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
from app.domains.email.providers.base import EmailMessage, SendResult
from app.domains.email.providers.console import ConsoleEmailProvider
from app.domains.email.repositories.email_delivery import EmailDeliveryRepository
from app.domains.email.repositories.notification_preferences import (
    NotificationPreferencesRepository,
)
from app.domains.email.services.email_service import EmailService
from app.domains.email.services.template_service import render_email_template
from app.main import app
from app.models.enums import (
    EmailDeliveryStatus,
    EmailEventType,
    OrganizationRole,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_delivery_repo = EmailDeliveryRepository()
_prefs_repo = NotificationPreferencesRepository()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def email_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "email_enabled", True)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_admin(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, Organization]:
    org = Organization(name=f"Email Org {uuid4().hex[:6]}", slug=f"email-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"email-user-{uuid4().hex[:8]}",
        email=f"admin-{uuid4().hex[:8]}@example.com",
        display_name="Email Admin",
    )
    db_session.add(user)
    await db_session.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=role.value,
    )
    db_session.add(member)
    await db_session.flush()
    return user, org


def _make_token(user: User, org: Organization) -> str:
    return create_app_access_token(
        user_id=str(user.id),
        organization_id=str(org.id),
        roles=[OrganizationRole.admin.value],
        issuer="rudix-test",
        audience="rudix-test-audience",
        secret=SecretStr("test-secret"),
        ttl_seconds=3600,
    )


# ---------------------------------------------------------------------------
# Template rendering tests
# ---------------------------------------------------------------------------


def test_render_invite_template() -> None:
    html = render_email_template(
        "invite.html",
        {
            "subject": "You are invited",
            "frontend_base_url": "http://localhost:3000",
            "org_name": "ACME Corp",
            "inviter_name": "Alice",
            "role": "member",
            "accept_url": "http://localhost:3000/accept-invite?token=abc",
            "recipient_name": "Bob",
        },
    )
    assert "ACME Corp" in html
    assert "Alice" in html
    assert "accept-invite" in html
    assert "member" in html


def test_render_upload_failure_template() -> None:
    html = render_email_template(
        "upload_failure.html",
        {
            "subject": "Upload failed",
            "frontend_base_url": "http://localhost:3000",
            "org_name": "ACME",
            "document_name": "report.pdf",
            "error_summary": "Extraction timeout",
        },
    )
    assert "report.pdf" in html
    assert "Extraction timeout" in html


def test_render_connector_sync_failure_template() -> None:
    html = render_email_template(
        "connector_sync_failure.html",
        {
            "subject": "Sync failed",
            "frontend_base_url": "http://localhost:3000",
            "org_name": "ACME",
            "connector_name": "Jira",
            "error_summary": "Rate limit exceeded",
            "failed_at": "2026-06-09 12:00",
        },
    )
    assert "Jira" in html
    assert "Rate limit exceeded" in html


def test_render_billing_warning_template() -> None:
    html = render_email_template(
        "billing_warning.html",
        {
            "subject": "Billing warning",
            "frontend_base_url": "http://localhost:3000",
            "org_name": "ACME",
            "warning_title": "Usage limit approaching",
            "warning_message": "You have used 90% of your monthly quota.",
        },
    )
    assert "90%" in html
    assert "Usage limit approaching" in html


def test_render_security_alert_template() -> None:
    html = render_email_template(
        "security_alert.html",
        {
            "subject": "Security Alert",
            "frontend_base_url": "http://localhost:3000",
            "org_name": "ACME",
            "alert_message": "An admin API key was rotated.",
            "occurred_at": "2026-06-09 15:30",
        },
    )
    assert "API key was rotated" in html
    assert "mandatory" in html


def test_render_template_missing_optional_values() -> None:
    """Templates must not raise when optional context vars are absent."""
    html = render_email_template(
        "invite.html",
        {
            "subject": "You are invited",
            "frontend_base_url": "http://localhost:3000",
            "org_name": "ACME",
            "role": "member",
            "accept_url": "http://example.com/accept",
        },
    )
    assert "ACME" in html


# ---------------------------------------------------------------------------
# Provider tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_console_provider_returns_success() -> None:
    provider = ConsoleEmailProvider()
    msg = EmailMessage(
        to_address="user@example.com",
        subject="Hello",
        html_body="<p>Hello</p>",
        from_address="noreply@example.com",
        from_name="Rudix",
    )
    result = await provider.send(msg)
    assert result.success is True
    assert provider.provider_name == "console"


@pytest.mark.asyncio
async def test_resend_provider_handles_http_error() -> None:
    from app.domains.email.providers.resend import ResendEmailProvider

    provider = ResendEmailProvider(api_key="test-key")
    msg = EmailMessage(
        to_address="user@example.com",
        subject="Hello",
        html_body="<p>Hello</p>",
        from_address="noreply@example.com",
        from_name="Rudix",
    )

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_post.return_value.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post.return_value.__aexit__ = AsyncMock(return_value=False)

        import httpx

        async with httpx.AsyncClient() as client:
            with patch.object(client, "post", return_value=mock_resp):
                pass

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        mock_client.post = AsyncMock(return_value=mock_resp)

        result = await provider.send(msg)
        assert result.success is False
        assert "401" in (result.error_detail or "")


@pytest.mark.asyncio
async def test_postmark_provider_handles_success() -> None:
    from app.domains.email.providers.postmark import PostmarkEmailProvider

    provider = PostmarkEmailProvider(server_token="test-token")
    msg = EmailMessage(
        to_address="user@example.com",
        subject="Hello",
        html_body="<p>Hello</p>",
        from_address="noreply@example.com",
        from_name="Rudix",
    )

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"MessageID": "pm-123"})
        mock_client.post = AsyncMock(return_value=mock_resp)

        result = await provider.send(msg)
        assert result.success is True
        assert result.provider_message_id == "pm-123"


# ---------------------------------------------------------------------------
# Preferences repository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preferences_default_enabled(db_session: AsyncSession) -> None:
    org = Organization(name=f"Pref Org {uuid4().hex[:4]}", slug=f"pref-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"pref-user-{uuid4().hex[:8]}",
        email=f"pref-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    result = await _prefs_repo.is_email_enabled(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.upload_failed,
    )
    assert result is True


@pytest.mark.asyncio
async def test_preferences_opt_out(db_session: AsyncSession) -> None:
    org = Organization(name=f"Opt Org {uuid4().hex[:4]}", slug=f"opt-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"opt-user-{uuid4().hex[:8]}",
        email=f"opt-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    await _prefs_repo.upsert_preference(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.upload_failed,
        email_enabled=False,
    )

    result = await _prefs_repo.is_email_enabled(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.upload_failed,
    )
    assert result is False


@pytest.mark.asyncio
async def test_preferences_upsert_idempotent(db_session: AsyncSession) -> None:
    org = Organization(name=f"Idmp Org {uuid4().hex[:4]}", slug=f"idmp-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"idmp-user-{uuid4().hex[:8]}",
        email=f"idmp-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    await _prefs_repo.upsert_preference(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.connector_sync_failed,
        email_enabled=False,
    )
    await _prefs_repo.upsert_preference(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.connector_sync_failed,
        email_enabled=True,
    )
    result = await _prefs_repo.is_email_enabled(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.connector_sync_failed,
    )
    assert result is True


# ---------------------------------------------------------------------------
# Delivery repository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_log_create_and_update(db_session: AsyncSession) -> None:
    org = Organization(name=f"Del Org {uuid4().hex[:4]}", slug=f"del-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"del-user-{uuid4().hex[:8]}",
        email=f"del-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    log_id = await _delivery_repo.create_log(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.invite_received,
        recipient_email="dest@example.com",
        subject="Test subject",
        provider="console",
    )
    await db_session.flush()

    await _delivery_repo.update_status(
        db_session,
        log_id=log_id,
        status=EmailDeliveryStatus.sent,
        provider_message_id="msg-001",
        error_detail=None,
    )

    logs = await _delivery_repo.list_logs(db_session, organization_id=org.id)
    assert len(logs) == 1
    assert logs[0].status == EmailDeliveryStatus.sent.value
    assert logs[0].provider_message_id == "msg-001"


@pytest.mark.asyncio
async def test_delivery_log_count(db_session: AsyncSession) -> None:
    org = Organization(name=f"Cnt Org {uuid4().hex[:4]}", slug=f"cnt-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"cnt-user-{uuid4().hex[:8]}",
        email=f"cnt-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    for _ in range(3):
        await _delivery_repo.create_log(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            event_type=EmailEventType.upload_failed,
            recipient_email="x@example.com",
            subject="Fail",
            provider="console",
        )
    await db_session.flush()
    total = await _delivery_repo.count_logs(db_session, organization_id=org.id)
    assert total == 3


# ---------------------------------------------------------------------------
# Email service tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_service_sends_when_enabled(db_session: AsyncSession) -> None:
    org = Organization(name=f"Svc Org {uuid4().hex[:4]}", slug=f"svc-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"svc-user-{uuid4().hex[:8]}",
        email=f"svc-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    mock_provider = AsyncMock()
    mock_provider.provider_name = "mock"
    mock_provider.send = AsyncMock(
        return_value=SendResult(success=True, provider_message_id="mock-001")
    )

    with patch.object(settings, "email_enabled", True):
        service = EmailService(provider=mock_provider)
        result = await service.send_email(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            recipient_email=user.email,
            event_type=EmailEventType.invite_received,
            template_name="invite.html",
            template_context={
                "org_name": org.name,
                "role": "member",
                "accept_url": "http://example.com/accept",
            },
            subject="You are invited",
        )

    assert result is True
    mock_provider.send.assert_called_once()


@pytest.mark.asyncio
async def test_email_service_skips_when_disabled(db_session: AsyncSession) -> None:
    org = Organization(name=f"Dis Org {uuid4().hex[:4]}", slug=f"dis-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"dis-user-{uuid4().hex[:8]}",
        email=f"dis-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    mock_provider = AsyncMock()
    mock_provider.provider_name = "mock"

    with patch.object(settings, "email_enabled", False):
        service = EmailService(provider=mock_provider)
        result = await service.send_email(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            recipient_email=user.email,
            event_type=EmailEventType.upload_failed,
            template_name="upload_failure.html",
            template_context={"org_name": org.name, "document_name": "test.pdf"},
            subject="Upload failed",
        )

    assert result is False
    mock_provider.send.assert_not_called()


@pytest.mark.asyncio
async def test_email_service_respects_opt_out(db_session: AsyncSession) -> None:
    org = Organization(name=f"Opt Org {uuid4().hex[:4]}", slug=f"opte-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"opte-user-{uuid4().hex[:8]}",
        email=f"opte-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    await _prefs_repo.upsert_preference(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.upload_failed,
        email_enabled=False,
    )

    mock_provider = AsyncMock()
    mock_provider.provider_name = "mock"

    with patch.object(settings, "email_enabled", True):
        service = EmailService(provider=mock_provider, prefs_repo=_prefs_repo)
        result = await service.send_email(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            recipient_email=user.email,
            event_type=EmailEventType.upload_failed,
            template_name="upload_failure.html",
            template_context={"org_name": org.name, "document_name": "doc.pdf"},
            subject="Upload failed",
        )

    assert result is False
    mock_provider.send.assert_not_called()


@pytest.mark.asyncio
async def test_mandatory_events_ignore_opt_out(db_session: AsyncSession) -> None:
    """invite_received and security_alert bypass preferences."""
    org = Organization(name=f"Mand Org {uuid4().hex[:4]}", slug=f"mand-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"mand-user-{uuid4().hex[:8]}",
        email=f"mand-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    await _prefs_repo.upsert_preference(
        db_session,
        organization_id=org.id,
        user_id=user.id,
        event_type=EmailEventType.invite_received,
        email_enabled=False,
    )

    mock_provider = AsyncMock()
    mock_provider.provider_name = "mock"
    mock_provider.send = AsyncMock(return_value=SendResult(success=True))

    with patch.object(settings, "email_enabled", True):
        service = EmailService(provider=mock_provider, prefs_repo=_prefs_repo)
        result = await service.send_email(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            recipient_email=user.email,
            event_type=EmailEventType.invite_received,
            template_name="invite.html",
            template_context={"org_name": org.name, "role": "member", "accept_url": "http://x.com"},
            subject="Invite",
        )

    assert result is True
    mock_provider.send.assert_called_once()


@pytest.mark.asyncio
async def test_email_service_logs_failure(db_session: AsyncSession) -> None:
    org = Organization(name=f"Fail Org {uuid4().hex[:4]}", slug=f"fail-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"fail-user-{uuid4().hex[:8]}",
        email=f"fail-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    mock_provider = AsyncMock()
    mock_provider.provider_name = "mock"
    mock_provider.send = AsyncMock(
        return_value=SendResult(success=False, error_detail="Connection refused")
    )

    with patch.object(settings, "email_enabled", True):
        service = EmailService(provider=mock_provider)
        result = await service.send_email(
            db_session,
            organization_id=org.id,
            user_id=user.id,
            recipient_email=user.email,
            event_type=EmailEventType.security_alert,
            template_name="security_alert.html",
            template_context={"org_name": org.name, "alert_message": "Key rotated"},
            subject="Security alert",
        )

    assert result is False
    logs = await _delivery_repo.list_logs(db_session, organization_id=org.id)
    assert any(log.status == EmailDeliveryStatus.failed.value for log in logs)
    assert any("Connection refused" in (log.error_detail or "") for log in logs)


# ---------------------------------------------------------------------------
# Admin API endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_template_endpoint(
    email_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = _make_token(user, org)
    resp = await email_client.post(
        "/api/v1/admin/email/preview",
        json={
            "template_name": "invite.html",
            "context": {
                "org_name": "ACME",
                "role": "member",
                "accept_url": "http://example.com/accept",
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "html" in data
    assert "ACME" in data["html"]


@pytest.mark.asyncio
async def test_preview_template_unknown_template(
    email_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = _make_token(user, org)
    resp = await email_client.post(
        "/api/v1/admin/email/preview",
        json={"template_name": "nonexistent.html", "context": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_test_send_blocked_in_production(
    email_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Environment

    monkeypatch.setattr(settings, "environment", Environment.production)
    user, org = await _seed_admin(db_session)
    token = _make_token(user, org)
    resp = await email_client.post(
        "/api/v1/admin/email/test-send",
        json={
            "recipient_email": "test@example.com",
            "event_type": "invite_received",
            "template_name": "invite.html",
            "subject": "Test",
            "context": {},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # In production env, test-send is blocked
    assert resp.status_code == 403
    # Reset environment to test after this check
    monkeypatch.setattr(
        settings,
        "environment",
        __import__("app.core.config", fromlist=["Environment"]).Environment.test,
    )


@pytest.mark.asyncio
async def test_test_send_success_non_production(
    email_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "email_enabled", True)
    monkeypatch.setattr(settings, "email_provider", "console")
    user, org = await _seed_admin(db_session)
    token = _make_token(user, org)
    resp = await email_client.post(
        "/api/v1/admin/email/test-send",
        json={
            "recipient_email": "test@example.com",
            "event_type": "invite_received",
            "template_name": "invite.html",
            "subject": "Test Invite",
            "context": {
                "org_name": "ACME",
                "role": "member",
                "accept_url": "http://example.com/accept",
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sent"] is True
    assert data["provider"] == "console"


@pytest.mark.asyncio
async def test_get_delivery_logs_endpoint(
    email_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = _make_token(user, org)
    resp = await email_client.get(
        "/api/v1/admin/email/delivery-logs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_preferences_returns_all_event_types(
    email_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = _make_token(user, org)
    resp = await email_client.get(
        "/api/v1/admin/email/preferences/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    event_types = {item["event_type"] for item in items}
    assert "invite_received" in event_types
    assert "upload_failed" in event_types
    assert "security_alert" in event_types


@pytest.mark.asyncio
async def test_update_preference_opt_out(
    email_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = _make_token(user, org)
    resp = await email_client.put(
        "/api/v1/admin/email/preferences/me",
        json={"event_type": "upload_failed", "email_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["event_type"] == "upload_failed"
    assert data["email_enabled"] is False


@pytest.mark.asyncio
async def test_update_preference_reject_mandatory_opt_out(
    email_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = _make_token(user, org)
    resp = await email_client.put(
        "/api/v1/admin/email/preferences/me",
        json={"event_type": "invite_received", "email_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preview_requires_auth(email_client: AsyncClient) -> None:
    resp = await email_client.post(
        "/api/v1/admin/email/preview",
        json={"template_name": "invite.html", "context": {}},
    )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Provider factory tests
# ---------------------------------------------------------------------------


def test_factory_returns_console_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "console")
    from app.domains.email.providers.console import ConsoleEmailProvider
    from app.domains.email.providers.factory import build_email_provider

    provider = build_email_provider()
    assert isinstance(provider, ConsoleEmailProvider)


def test_factory_resend_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "resend")
    monkeypatch.setattr(settings, "resend_api_key", None)
    from app.domains.email.providers.factory import build_email_provider

    with pytest.raises(ValueError, match="resend_api_key"):
        build_email_provider()


def test_factory_postmark_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "postmark")
    monkeypatch.setattr(settings, "postmark_server_token", None)
    from app.domains.email.providers.factory import build_email_provider

    with pytest.raises(ValueError, match="postmark_server_token"):
        build_email_provider()


def test_factory_smtp_builds_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_provider", "smtp")
    from app.domains.email.providers.factory import build_email_provider
    from app.domains.email.providers.smtp import SMTPEmailProvider

    provider = build_email_provider()
    assert isinstance(provider, SMTPEmailProvider)


# ---------------------------------------------------------------------------
# SMTP provider smoke tests (no real connection)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smtp_provider_handles_connection_error() -> None:
    from app.domains.email.providers.smtp import SMTPEmailProvider

    provider = SMTPEmailProvider(
        host="127.0.0.1",
        port=9999,
        username=None,
        password=None,
        use_tls=False,
        timeout_seconds=0.5,
    )
    msg = EmailMessage(
        to_address="user@example.com",
        subject="Hello",
        html_body="<p>Hello</p>",
        from_address="noreply@example.com",
        from_name="Rudix",
    )
    result = await provider.send(msg)
    assert result.success is False
    assert result.error_detail is not None
