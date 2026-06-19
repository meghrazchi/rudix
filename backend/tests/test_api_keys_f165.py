"""Tests for F165: API keys management.

Covers:
- Key creation (hashing, prefix, scopes)
- Key listing (org-scoped)
- Key retrieval
- Key update (name/description)
- Key revocation
- Key rotation
- Permission enforcement (forbidden states)
- Scope enforcement via require_permission
- Revoked/expired key authentication
- Raw key not stored/logged in response
- Security: raw key only returned at creation
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
from app.domains.api_keys.services.api_keys_service import ApiKeysService
from app.domains.quota.services.quota_service import upsert_policy_with_log
from app.main import app
from app.models.api_key import ApiKey
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_keys_client(
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
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_org_actor(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    org_prefix: str = "apikeys",
) -> tuple[User, Organization]:
    org = Organization(
        name=f"{org_prefix}-{uuid4().hex[:8]}",
        slug=f"{org_prefix}-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"actor-{uuid4().hex[:8]}",
        email=f"actor-{uuid4().hex[:8]}@example.com",
        display_name="Actor",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, org


async def _seed_quota_policy(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    limits: dict[str, dict[str, object]],
) -> None:
    await upsert_policy_with_log(
        db_session,
        organization_id=organization_id,
        limits=limits,
        updated_by_id=None,
        change_note="test quota policy",
    )
    await db_session.commit()


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


def _token(user: User, org: Organization) -> str:
    return create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )


# ─── ApiKeysService unit tests ────────────────────────────────────────────────


class TestApiKeysService:
    def test_generate_raw_key_has_prefix(self) -> None:
        key = ApiKeysService.generate_raw_key()
        assert key.startswith("rudix_")

    def test_generate_raw_key_is_unique(self) -> None:
        keys = {ApiKeysService.generate_raw_key() for _ in range(100)}
        assert len(keys) == 100

    def test_hash_key_is_deterministic(self) -> None:
        key = ApiKeysService.generate_raw_key()
        assert ApiKeysService.hash_key(key) == ApiKeysService.hash_key(key)

    def test_hash_key_is_64_hex_chars(self) -> None:
        key = ApiKeysService.generate_raw_key()
        h = ApiKeysService.hash_key(key)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_differs_for_different_keys(self) -> None:
        k1 = ApiKeysService.generate_raw_key()
        k2 = ApiKeysService.generate_raw_key()
        assert ApiKeysService.hash_key(k1) != ApiKeysService.hash_key(k2)

    def test_key_prefix_length(self) -> None:
        key = ApiKeysService.generate_raw_key()
        prefix = ApiKeysService.key_prefix(key)
        assert len(prefix) == 16
        assert key.startswith(prefix)

    def test_not_expired_when_no_expiry(self) -> None:
        api_key = ApiKey(
            organization_id=uuid4(),
            name="test",
            key_prefix="rudix_xxxxxxxxx",
            key_hash="abc",
            scopes=[],
        )
        api_key.expires_at = None
        assert ApiKeysService.is_expired(api_key) is False

    def test_expired_when_past_expiry(self) -> None:
        api_key = ApiKey(
            organization_id=uuid4(),
            name="test",
            key_prefix="rudix_xxxxxxxxx",
            key_hash="abc",
            scopes=[],
        )
        api_key.expires_at = datetime.now(tz=UTC) - timedelta(hours=1)
        assert ApiKeysService.is_expired(api_key) is True

    def test_not_expired_when_future_expiry(self) -> None:
        api_key = ApiKey(
            organization_id=uuid4(),
            name="test",
            key_prefix="rudix_xxxxxxxxx",
            key_hash="abc",
            scopes=[],
        )
        api_key.expires_at = datetime.now(tz=UTC) + timedelta(hours=1)
        assert ApiKeysService.is_expired(api_key) is False

    def test_scopes_to_permissions_documents_read(self) -> None:
        perms = ApiKeysService.scopes_to_permissions(["documents:read"])
        assert "documents:view" in perms
        assert "documents:upload" not in perms

    def test_scopes_to_permissions_documents_write(self) -> None:
        perms = ApiKeysService.scopes_to_permissions(["documents:write"])
        assert "documents:view" in perms
        assert "documents:upload" in perms
        assert "documents:manage" in perms

    def test_scopes_to_permissions_chat_write(self) -> None:
        perms = ApiKeysService.scopes_to_permissions(["chat:write"])
        assert "chat:use" in perms
        assert "chat:use_collections" in perms

    def test_scopes_to_permissions_combined(self) -> None:
        perms = ApiKeysService.scopes_to_permissions(["documents:read", "chat:write"])
        assert "documents:view" in perms
        assert "chat:use" in perms

    def test_scopes_to_permissions_empty(self) -> None:
        perms = ApiKeysService.scopes_to_permissions([])
        assert len(perms) == 0


# ─── API endpoint tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_api_key_success(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)

    response = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "CI integration key",
            "description": "Used by CI pipeline",
            "scopes": ["documents:read", "chat:write"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "CI integration key"
    assert payload["scopes"] == ["documents:read", "chat:write"]
    assert payload["status"] == "active"
    assert "raw_key" in payload
    assert payload["raw_key"].startswith("rudix_")
    assert payload["key_prefix"] == payload["raw_key"][:16]


@pytest.mark.asyncio
async def test_create_api_key_raw_key_not_in_list(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Raw key must not appear in list or get responses — only on creation."""
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=headers,
        json={"name": "Secret key", "scopes": []},
    )
    assert create_resp.status_code == 201

    list_resp = await api_keys_client.get("/api/v1/admin/api-keys", headers=headers)
    assert list_resp.status_code == 200
    for item in list_resp.json()["items"]:
        assert "raw_key" not in item


@pytest.mark.asyncio
async def test_create_api_key_invalid_scope_rejected(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)

    response = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"name": "Bad key", "scopes": ["not:a:valid:scope"]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_api_key_forbidden_for_viewer(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.viewer)
    token = _token(actor, org)

    response = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"name": "Forbidden key", "scopes": []},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_api_key_blocks_when_api_call_quota_is_exhausted(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    await _seed_quota_policy(
        db_session,
        organization_id=org.id,
        limits={
            "api_calls": {
                "soft_limit": 0,
                "hard_limit": 0,
                "reset_window": "per_minute",
            }
        },
    )
    token = _token(actor, org)

    response = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"name": "Blocked key", "scopes": []},
    )

    assert response.status_code == 403
    payload = response.json()["detail"]
    assert payload["code"] == "plan_limit_exceeded"
    assert payload["quota_type"] == "api_calls"
    assert payload["retryable"] is True
    assert payload["action"] == "Wait a moment and retry or upgrade your plan."


@pytest.mark.asyncio
async def test_list_api_keys_empty(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)

    response = await api_keys_client.get(
        "/api/v1/admin/api-keys",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0


@pytest.mark.asyncio
async def test_list_api_keys_returns_created_keys(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    for i in range(3):
        await api_keys_client.post(
            "/api/v1/admin/api-keys",
            headers=headers,
            json={"name": f"Key {i}", "scopes": []},
        )

    response = await api_keys_client.get("/api/v1/admin/api-keys", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 3


@pytest.mark.asyncio
async def test_api_keys_are_org_scoped(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor1, org1 = await _seed_org_actor(
        db_session, role=OrganizationRole.admin, org_prefix="ak-org1"
    )
    actor2, org2 = await _seed_org_actor(
        db_session, role=OrganizationRole.admin, org_prefix="ak-org2"
    )

    await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=_auth_headers(token=_token(actor1, org1), organization_id=str(org1.id)),
        json={"name": "Org1 key", "scopes": []},
    )

    response = await api_keys_client.get(
        "/api/v1/admin/api-keys",
        headers=_auth_headers(token=_token(actor2, org2), organization_id=str(org2.id)),
    )
    payload = response.json()
    names = [item["name"] for item in payload["items"]]
    assert "Org1 key" not in names


@pytest.mark.asyncio
async def test_get_api_key_by_id(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=headers,
        json={"name": "Fetchable", "scopes": ["documents:read"]},
    )
    key_id = create_resp.json()["id"]

    response = await api_keys_client.get(f"/api/v1/admin/api-keys/{key_id}", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == key_id
    assert "raw_key" not in payload


@pytest.mark.asyncio
async def test_get_api_key_not_found(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)

    response = await api_keys_client.get(
        f"/api/v1/admin/api-keys/{uuid4()}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_api_key_name(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=headers,
        json={"name": "Old name", "scopes": []},
    )
    key_id = create_resp.json()["id"]

    patch_resp = await api_keys_client.patch(
        f"/api/v1/admin/api-keys/{key_id}",
        headers=headers,
        json={"name": "New name"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "New name"


@pytest.mark.asyncio
async def test_revoke_api_key(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=headers,
        json={"name": "Revokable key", "scopes": []},
    )
    key_id = create_resp.json()["id"]

    revoke_resp = await api_keys_client.delete(f"/api/v1/admin/api-keys/{key_id}", headers=headers)
    assert revoke_resp.status_code == 204

    get_resp = await api_keys_client.get(f"/api/v1/admin/api-keys/{key_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_revoke_already_revoked_key_returns_409(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=headers,
        json={"name": "Double revoke", "scopes": []},
    )
    key_id = create_resp.json()["id"]

    await api_keys_client.delete(f"/api/v1/admin/api-keys/{key_id}", headers=headers)
    second = await api_keys_client.delete(f"/api/v1/admin/api-keys/{key_id}", headers=headers)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_rotate_api_key(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=headers,
        json={"name": "Rotate me", "scopes": ["documents:read"]},
    )
    old_id = create_resp.json()["id"]
    old_raw_key = create_resp.json()["raw_key"]

    rotate_resp = await api_keys_client.post(
        f"/api/v1/admin/api-keys/{old_id}/rotate", headers=headers
    )
    assert rotate_resp.status_code == 201
    new_payload = rotate_resp.json()
    assert new_payload["id"] != old_id
    assert new_payload["raw_key"] != old_raw_key
    assert new_payload["raw_key"].startswith("rudix_")
    assert new_payload["name"] == "Rotate me"
    assert new_payload["scopes"] == ["documents:read"]

    old_resp = await api_keys_client.get(f"/api/v1/admin/api-keys/{old_id}", headers=headers)
    assert old_resp.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_api_key_auth_bearer_token(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """An active API key used as a bearer token should allow scoped requests."""
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=headers,
        json={"name": "Auth test key", "scopes": ["documents:read"]},
    )
    raw_key = create_resp.json()["raw_key"]

    # Use the raw key directly as a bearer token (no x-organization-id needed)
    list_resp = await api_keys_client.get(
        "/api/v1/admin/api-keys",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    # The key has no api_keys:list scope, so should be 403
    assert list_resp.status_code == 403


@pytest.mark.asyncio
async def test_revoked_api_key_auth_rejected(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await api_keys_client.post(
        "/api/v1/admin/api-keys",
        headers=headers,
        json={"name": "Revoked auth key", "scopes": ["documents:read"]},
    )
    raw_key = create_resp.json()["raw_key"]
    key_id = create_resp.json()["id"]

    await api_keys_client.delete(f"/api/v1/admin/api-keys/{key_id}", headers=headers)

    resp = await api_keys_client.get(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_invalid_api_key_auth_rejected(
    api_keys_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    resp = await api_keys_client.get(
        "/api/v1/documents",
        headers={"Authorization": "Bearer rudix_thiskeydoesnotexist123456789012345"},
    )
    assert resp.status_code == 401
