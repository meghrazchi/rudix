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
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.models.webhook import Webhook


@pytest_asyncio.fixture
async def admin_client(
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
    role: OrganizationRole,
) -> tuple[User, Organization]:
    org = Organization(name=f"Org-{uuid4().hex[:8]}", slug=f"org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Test Admin",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


async def _seed_webhook(
    db_session: AsyncSession,
    *,
    organization_id: object,
    name: str = "My webhook",
    url: str = "https://example.com/hook",
    status: str = "active",
    event_types: list[str] | None = None,
) -> Webhook:
    webhook = Webhook(
        organization_id=organization_id,
        name=name,
        url=url,
        secret_prefix="whsec_testprefix",
        secret_hash="a" * 64,
        event_types=event_types or ["document.indexed"],
        status=status,
        retry_policy={"max_attempts": 3, "backoff_seconds": 30},
    )
    db_session.add(webhook)
    await db_session.commit()
    return webhook


# ─── List ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_webhooks_empty_for_new_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/webhooks", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_webhooks_scoped_to_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    _, other_org = await _seed_principal(db_session, role=OrganizationRole.admin)

    await _seed_webhook(db_session, organization_id=org.id, name="Mine")
    await _seed_webhook(db_session, organization_id=other_org.id, name="Other org")

    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        "/admin/webhooks", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["name"] == "Mine"


@pytest.mark.asyncio
async def test_list_webhooks_forbidden_for_viewer(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.viewer)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.viewer.value
    )
    response = await admin_client.get(
        "/admin/webhooks", headers=_auth_headers(token=token, organization_id=str(org.id))
    )
    assert response.status_code == 403


# ─── Create ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_webhook_returns_raw_secret(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        "/admin/webhooks",
        json={
            "name": "Doc events",
            "url": "https://receiver.example.com/hook",
            "event_types": ["document.indexed", "document.failed"],
        },
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Doc events"
    assert data["raw_secret"].startswith("whsec_")
    assert "raw_secret" in data
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_webhook_rejects_ssrf_url(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    for bad_url in [
        "http://localhost/hook",
        "http://127.0.0.1/hook",
        "http://192.168.1.1/hook",
        "http://10.0.0.1/hook",
        "file:///etc/passwd",
    ]:
        response = await admin_client.post(
            "/admin/webhooks",
            json={"name": "Bad", "url": bad_url, "event_types": []},
            headers=_auth_headers(token=token, organization_id=str(org.id)),
        )
        assert response.status_code == 422, f"Expected 422 for {bad_url}"


@pytest.mark.asyncio
async def test_create_webhook_rejects_unknown_event_types(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        "/admin/webhooks",
        json={
            "name": "Bad",
            "url": "https://example.com/hook",
            "event_types": ["not.a.real.event"],
        },
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_webhook_forbidden_for_developer_without_create(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.member.value
    )
    response = await admin_client.post(
        "/admin/webhooks",
        json={"name": "X", "url": "https://example.com/hook", "event_types": []},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ─── Get ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_webhook_returns_correct_item(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    webhook = await _seed_webhook(db_session, organization_id=org.id, name="Target")
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        f"/admin/webhooks/{webhook.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Target"


@pytest.mark.asyncio
async def test_get_webhook_404_for_other_org(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    _, other_org = await _seed_principal(db_session, role=OrganizationRole.admin)
    webhook = await _seed_webhook(db_session, organization_id=other_org.id)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        f"/admin/webhooks/{webhook.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


# ─── Update ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_webhook_name_and_status(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    webhook = await _seed_webhook(db_session, organization_id=org.id)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.patch(
        f"/admin/webhooks/{webhook.id}",
        json={"name": "Updated name", "status": "disabled"},
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated name"
    assert data["status"] == "disabled"


# ─── Delete ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_webhook_returns_204(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    webhook = await _seed_webhook(db_session, organization_id=org.id)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.delete(
        f"/admin/webhooks/{webhook.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 204

    # Confirm it's gone
    get_response = await admin_client.get(
        f"/admin/webhooks/{webhook.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_delete_webhook_not_found(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.delete(
        f"/admin/webhooks/{uuid4()}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


# ─── Rotate secret ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rotate_secret_returns_new_raw_secret(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    webhook = await _seed_webhook(db_session, organization_id=org.id)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.post(
        f"/admin/webhooks/{webhook.id}/rotate-secret",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["raw_secret"].startswith("whsec_")
    assert data["secret_prefix"] != "whsec_testprefix"


# ─── Deliveries ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_deliveries_empty_initially(
    admin_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session, role=OrganizationRole.admin)
    webhook = await _seed_webhook(db_session, organization_id=org.id)
    token = create_app_access_token(
        user_id=str(user.id), organization_id=str(org.id), role=OrganizationRole.admin.value
    )
    response = await admin_client.get(
        f"/admin/webhooks/{webhook.id}/deliveries",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


# ─── Signing service unit tests ───────────────────────────────────────────────


def test_sign_payload_produces_deterministic_hmac() -> None:
    from app.domains.webhooks.services.webhooks_service import WebhooksService

    secret = WebhooksService.generate_raw_secret()
    body = b'{"event":"document.indexed"}'
    sig1, _ts = WebhooksService.sign_payload(secret, body, timestamp=1234567890)
    sig2, _ = WebhooksService.sign_payload(secret, body, timestamp=1234567890)
    assert sig1 == sig2
    assert len(sig1) == 64  # SHA-256 hex


def test_sign_payload_different_for_different_secrets() -> None:
    from app.domains.webhooks.services.webhooks_service import WebhooksService

    s1 = WebhooksService.generate_raw_secret()
    s2 = WebhooksService.generate_raw_secret()
    body = b'{"event":"test"}'
    sig1, _ = WebhooksService.sign_payload(s1, body, timestamp=1)
    sig2, _ = WebhooksService.sign_payload(s2, body, timestamp=1)
    assert sig1 != sig2


def test_hash_secret_is_sha256_hex() -> None:
    from app.domains.webhooks.services.webhooks_service import WebhooksService

    raw = "whsec_test"
    h = WebhooksService.hash_secret(raw)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_ssrf_validation_rejects_private_ips() -> None:
    from app.domains.webhooks.schemas.webhooks import _is_ssrf_risk

    assert _is_ssrf_risk("http://localhost/hook") is True
    assert _is_ssrf_risk("http://127.0.0.1/hook") is True
    assert _is_ssrf_risk("http://192.168.0.1/hook") is True
    assert _is_ssrf_risk("http://10.1.2.3/hook") is True
    assert _is_ssrf_risk("http://172.20.0.1/hook") is True
    assert _is_ssrf_risk("file:///etc/passwd") is True
    assert _is_ssrf_risk("ftp://example.com/file") is True


def test_ssrf_validation_allows_public_urls() -> None:
    from app.domains.webhooks.schemas.webhooks import _is_ssrf_risk

    assert _is_ssrf_risk("https://example.com/hook") is False
    assert _is_ssrf_risk("https://my-service.io/api/webhook") is False
    assert _is_ssrf_risk("http://external.example.org/events") is False
