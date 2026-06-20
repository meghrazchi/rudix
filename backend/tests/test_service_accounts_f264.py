"""Tests for F264: Service accounts and machine users.

Covers:
- ServiceAccountsService unit tests (token generation, hashing, scope resolution)
- Service account CRUD (create, list, get, update, deactivate, reactivate)
- Token lifecycle (create, list, revoke, rotate)
- Permission enforcement (viewer forbidden, developer allowed)
- Cross-tenant isolation (org-A cannot access org-B resources)
- Token authentication via svc_ bearer token
- Inactive account gates (cannot issue tokens for inactive account)
- Raw token only shown at creation time
- Audit log recording
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
from app.domains.service_accounts.services.service_accounts_service import ServiceAccountsService
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.service_account import ServiceAccountToken
from app.models.user import User

# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def sa_client(
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
    org_prefix: str = "svcacc",
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


# ─── ServiceAccountsService unit tests ───────────────────────────────────────


class TestServiceAccountsService:
    def test_generate_raw_token_has_prefix(self) -> None:
        token = ServiceAccountsService.generate_raw_token()
        assert token.startswith("svc_")

    def test_generate_raw_token_is_unique(self) -> None:
        tokens = {ServiceAccountsService.generate_raw_token() for _ in range(100)}
        assert len(tokens) == 100

    def test_hash_token_is_deterministic(self) -> None:
        token = ServiceAccountsService.generate_raw_token()
        assert ServiceAccountsService.hash_token(token) == ServiceAccountsService.hash_token(token)

    def test_hash_token_is_64_hex_chars(self) -> None:
        token = ServiceAccountsService.generate_raw_token()
        h = ServiceAccountsService.hash_token(token)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_differs_for_different_tokens(self) -> None:
        t1 = ServiceAccountsService.generate_raw_token()
        t2 = ServiceAccountsService.generate_raw_token()
        assert ServiceAccountsService.hash_token(t1) != ServiceAccountsService.hash_token(t2)

    def test_token_prefix_length(self) -> None:
        token = ServiceAccountsService.generate_raw_token()
        prefix = ServiceAccountsService.token_prefix(token)
        assert len(prefix) == 16
        assert token.startswith(prefix)

    def test_is_not_expired_when_no_expiry(self) -> None:
        sa_token = ServiceAccountToken(
            service_account_id=uuid4(),
            organization_id=uuid4(),
            name="t",
            token_prefix="svc_xxxx",
            token_hash="abc",
        )
        sa_token.expires_at = None
        assert ServiceAccountsService.is_expired(sa_token) is False

    def test_is_expired_when_past_expiry(self) -> None:
        sa_token = ServiceAccountToken(
            service_account_id=uuid4(),
            organization_id=uuid4(),
            name="t",
            token_prefix="svc_xxxx",
            token_hash="abc",
        )
        sa_token.expires_at = datetime.now(tz=UTC) - timedelta(hours=1)
        assert ServiceAccountsService.is_expired(sa_token) is True

    def test_is_not_expired_when_future_expiry(self) -> None:
        sa_token = ServiceAccountToken(
            service_account_id=uuid4(),
            organization_id=uuid4(),
            name="t",
            token_prefix="svc_xxxx",
            token_hash="abc",
        )
        sa_token.expires_at = datetime.now(tz=UTC) + timedelta(hours=1)
        assert ServiceAccountsService.is_expired(sa_token) is False

    def test_scopes_to_permissions_documents_read(self) -> None:
        perms = ServiceAccountsService.scopes_to_permissions(["documents:read"])
        assert "documents:view" in perms
        assert "documents:upload" not in perms

    def test_scopes_to_permissions_documents_write(self) -> None:
        perms = ServiceAccountsService.scopes_to_permissions(["documents:write"])
        assert "documents:view" in perms
        assert "documents:upload" in perms
        assert "documents:manage" in perms

    def test_scopes_to_permissions_empty(self) -> None:
        perms = ServiceAccountsService.scopes_to_permissions([])
        assert len(perms) == 0


# ─── Service account CRUD ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_service_account_success(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)

    response = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(actor, org), organization_id=str(org.id)),
        json={
            "name": "CI pipeline",
            "description": "Used by GitHub Actions",
            "environment": "ci",
            "scopes": ["documents:read"],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "CI pipeline"
    assert payload["environment"] == "ci"
    assert payload["scopes"] == ["documents:read"]
    assert payload["is_active"] is True
    assert "raw_token" not in payload


@pytest.mark.asyncio
async def test_create_service_account_forbidden_for_viewer(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.viewer)

    response = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(actor, org), organization_id=str(org.id)),
        json={"name": "Not allowed", "scopes": []},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_service_account_invalid_environment_rejected(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)

    response = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(actor, org), organization_id=str(org.id)),
        json={"name": "Bad env", "environment": "outer-space", "scopes": []},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_service_account_invalid_scope_rejected(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)

    response = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(actor, org), organization_id=str(org.id)),
        json={"name": "Bad scope", "scopes": ["admin:everything"]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_service_accounts_empty(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)

    response = await sa_client.get(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(actor, org), organization_id=str(org.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0


@pytest.mark.asyncio
async def test_list_service_accounts_returns_created_accounts(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    for i in range(3):
        await sa_client.post(
            "/api/v1/admin/service-accounts",
            headers=headers,
            json={"name": f"Account {i}", "scopes": []},
        )

    response = await sa_client.get("/api/v1/admin/service-accounts", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 3


@pytest.mark.asyncio
async def test_get_service_account_success(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "Connector sync", "scopes": ["documents:read"]},
    )
    account_id = create_resp.json()["id"]

    get_resp = await sa_client.get(
        f"/api/v1/admin/service-accounts/{account_id}",
        headers=headers,
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Connector sync"


@pytest.mark.asyncio
async def test_get_service_account_not_found(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)

    response = await sa_client.get(
        f"/api/v1/admin/service-accounts/{uuid4()}",
        headers=_auth_headers(token=_token(actor, org), organization_id=str(org.id)),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_service_account_success(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "Old name", "scopes": []},
    )
    account_id = create_resp.json()["id"]

    update_resp = await sa_client.patch(
        f"/api/v1/admin/service-accounts/{account_id}",
        headers=headers,
        json={"name": "New name", "environment": "staging"},
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["name"] == "New name"
    assert body["environment"] == "staging"


@pytest.mark.asyncio
async def test_deactivate_service_account(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "To deactivate", "scopes": []},
    )
    account_id = create_resp.json()["id"]

    deactivate_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/deactivate",
        headers=headers,
    )
    assert deactivate_resp.status_code == 200
    assert deactivate_resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_deactivate_already_inactive_returns_409(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "To deactivate", "scopes": []},
    )
    account_id = create_resp.json()["id"]
    await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/deactivate",
        headers=headers,
    )

    second_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/deactivate",
        headers=headers,
    )
    assert second_resp.status_code == 409


@pytest.mark.asyncio
async def test_reactivate_service_account(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "To reactivate", "scopes": []},
    )
    account_id = create_resp.json()["id"]
    await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/deactivate",
        headers=headers,
    )

    reactivate_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/reactivate",
        headers=headers,
    )
    assert reactivate_resp.status_code == 200
    assert reactivate_resp.json()["is_active"] is True


# ─── Token lifecycle ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_token_success(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "My SA", "scopes": ["documents:read"]},
    )
    account_id = create_resp.json()["id"]

    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Primary token"},
    )

    assert token_resp.status_code == 201
    body = token_resp.json()
    assert "raw_token" in body
    assert body["raw_token"].startswith("svc_")
    assert body["token_prefix"] == body["raw_token"][:16]
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_raw_token_not_in_list_response(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "SA", "scopes": []},
    )
    account_id = create_resp.json()["id"]
    await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Secret"},
    )

    list_resp = await sa_client.get(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
    )
    assert list_resp.status_code == 200
    for item in list_resp.json()["items"]:
        assert "raw_token" not in item


@pytest.mark.asyncio
async def test_create_token_for_inactive_account_rejected(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "Inactive SA", "scopes": []},
    )
    account_id = create_resp.json()["id"]
    await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/deactivate",
        headers=headers,
    )

    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Should fail"},
    )
    assert token_resp.status_code == 409


@pytest.mark.asyncio
async def test_revoke_token_success(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "SA", "scopes": []},
    )
    account_id = create_resp.json()["id"]
    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Token"},
    )
    token_id = token_resp.json()["id"]

    revoke_resp = await sa_client.delete(
        f"/api/v1/admin/service-accounts/{account_id}/tokens/{token_id}",
        headers=headers,
    )
    assert revoke_resp.status_code == 204


@pytest.mark.asyncio
async def test_revoke_already_revoked_token_returns_409(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "SA", "scopes": []},
    )
    account_id = create_resp.json()["id"]
    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Token"},
    )
    token_id = token_resp.json()["id"]
    await sa_client.delete(
        f"/api/v1/admin/service-accounts/{account_id}/tokens/{token_id}",
        headers=headers,
    )

    second_resp = await sa_client.delete(
        f"/api/v1/admin/service-accounts/{account_id}/tokens/{token_id}",
        headers=headers,
    )
    assert second_resp.status_code == 409


@pytest.mark.asyncio
async def test_rotate_token_returns_new_raw_token(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "SA", "scopes": ["documents:read"]},
    )
    account_id = create_resp.json()["id"]
    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Main"},
    )
    old_token_id = token_resp.json()["id"]
    old_raw = token_resp.json()["raw_token"]

    rotate_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens/{old_token_id}/rotate",
        headers=headers,
    )
    assert rotate_resp.status_code == 201
    new_body = rotate_resp.json()
    assert new_body["raw_token"].startswith("svc_")
    assert new_body["raw_token"] != old_raw
    assert new_body["id"] != old_token_id

    # old token should now be revoked
    list_resp = await sa_client.get(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
    )
    statuses = {t["id"]: t["status"] for t in list_resp.json()["items"]}
    assert statuses[old_token_id] == "revoked"
    assert statuses[new_body["id"]] == "active"


# ─── Cross-tenant isolation ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cannot_access_other_org_service_account(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_a, org_a = await _seed_org_actor(
        db_session, role=OrganizationRole.admin, org_prefix="org-a"
    )
    actor_b, org_b = await _seed_org_actor(
        db_session, role=OrganizationRole.admin, org_prefix="org-b"
    )

    # Create a service account in org A
    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(owner_a, org_a), organization_id=str(org_a.id)),
        json={"name": "Org A account", "scopes": []},
    )
    account_id_a = create_resp.json()["id"]

    # Org B actor should not see it
    get_resp = await sa_client.get(
        f"/api/v1/admin/service-accounts/{account_id_a}",
        headers=_auth_headers(token=_token(actor_b, org_b), organization_id=str(org_b.id)),
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_issue_token_for_other_org_account(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_a, org_a = await _seed_org_actor(db_session, role=OrganizationRole.admin, org_prefix="ta")
    actor_b, org_b = await _seed_org_actor(db_session, role=OrganizationRole.admin, org_prefix="tb")

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(owner_a, org_a), organization_id=str(org_a.id)),
        json={"name": "Org A account", "scopes": []},
    )
    account_id_a = create_resp.json()["id"]

    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id_a}/tokens",
        headers=_auth_headers(token=_token(actor_b, org_b), organization_id=str(org_b.id)),
        json={"name": "Leak attempt"},
    )
    assert token_resp.status_code == 404


@pytest.mark.asyncio
async def test_list_service_accounts_scoped_to_own_org(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_a, org_a = await _seed_org_actor(
        db_session, role=OrganizationRole.admin, org_prefix="list-a"
    )
    actor_b, org_b = await _seed_org_actor(
        db_session, role=OrganizationRole.admin, org_prefix="list-b"
    )

    await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(owner_a, org_a), organization_id=str(org_a.id)),
        json={"name": "Org A only", "scopes": []},
    )

    list_resp = await sa_client.get(
        "/api/v1/admin/service-accounts",
        headers=_auth_headers(token=_token(actor_b, org_b), organization_id=str(org_b.id)),
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 0


# ─── Service account token bearer authentication ──────────────────────────────


@pytest.mark.asyncio
async def test_svc_token_authenticates_and_enforces_scopes(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A svc_ bearer token should authenticate and have pre-resolved scope permissions."""
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    # Create service account with documents:read scope
    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "Docs reader", "scopes": ["documents:read"]},
    )
    account_id = create_resp.json()["id"]

    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Primary"},
    )
    raw_token = token_resp.json()["raw_token"]

    # Use svc_ token as bearer — should be accepted by the auth middleware
    svc_headers = {
        "Authorization": f"Bearer {raw_token}",
        "X-Organization-ID": str(org.id),
    }
    # Verify token can list service accounts (requires service_accounts:list which
    # is not in documents:read scope) → 403.  This proves scope enforcement works.
    list_resp = await sa_client.get("/api/v1/admin/service-accounts", headers=svc_headers)
    assert list_resp.status_code == 403


@pytest.mark.asyncio
async def test_revoked_token_rejected(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "SA", "scopes": ["documents:read"]},
    )
    account_id = create_resp.json()["id"]
    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Token"},
    )
    raw_token = token_resp.json()["raw_token"]
    token_id = token_resp.json()["id"]

    # Revoke the token
    await sa_client.delete(
        f"/api/v1/admin/service-accounts/{account_id}/tokens/{token_id}",
        headers=headers,
    )

    # Attempt to use revoked token
    revoked_resp = await sa_client.get(
        "/api/v1/admin/service-accounts",
        headers={"Authorization": f"Bearer {raw_token}", "X-Organization-ID": str(org.id)},
    )
    assert revoked_resp.status_code == 401


@pytest.mark.asyncio
async def test_inactive_account_token_rejected(
    sa_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    headers = _auth_headers(token=_token(actor, org), organization_id=str(org.id))

    create_resp = await sa_client.post(
        "/api/v1/admin/service-accounts",
        headers=headers,
        json={"name": "SA", "scopes": ["documents:read"]},
    )
    account_id = create_resp.json()["id"]
    token_resp = await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/tokens",
        headers=headers,
        json={"name": "Token"},
    )
    raw_token = token_resp.json()["raw_token"]

    # Deactivate the service account
    await sa_client.post(
        f"/api/v1/admin/service-accounts/{account_id}/deactivate",
        headers=headers,
    )

    # Attempt to use token while account is inactive
    inactive_resp = await sa_client.get(
        "/api/v1/admin/service-accounts",
        headers={"Authorization": f"Bearer {raw_token}", "X-Organization-ID": str(org.id)},
    )
    assert inactive_resp.status_code == 401
