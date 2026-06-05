"""SCIM provisioning and domain verification tests (F161)."""
from __future__ import annotations

import hashlib
import os
import secrets
from unittest.mock import patch
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
os.environ.setdefault("APP_AUTH_SECRET", "test-secret-scim")

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.scim.services.scim_service import _hash_token
from app.main import app
from app.models.enums import OrganizationRole
from app.models.org_domain_verification import OrgDomainVerification
from app.models.org_scim_config import OrgSCIMConfig
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def scim_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret-scim"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def _seed_owner(db_session: AsyncSession) -> tuple[User, Organization]:
    org = Organization(
        name=f"SCIM Org {uuid4().hex[:6]}", slug=f"scim-org-{uuid4().hex[:8]}"
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"scim-owner-{uuid4().hex[:8]}",
        email=f"owner-{uuid4().hex[:6]}@scimtest.com",
        display_name="SCIM Owner",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.owner.value,
        )
    )
    await db_session.commit()
    return user, org


async def _seed_member(db_session: AsyncSession, org: Organization) -> User:
    user = User(
        organization_id=org.id,
        external_auth_id=f"scim-member-{uuid4().hex[:8]}",
        email=f"member-{uuid4().hex[:6]}@scimtest.com",
        display_name="SCIM Member",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()
    return user


def _bearer(user: User, org: Organization) -> str:
    return create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        email=user.email,
    )


async def _seed_scim_config(
    db_session: AsyncSession, org: Organization, *, raw_token: str | None = None
) -> tuple[OrgSCIMConfig, str]:
    raw = raw_token or secrets.token_hex(32)
    config = OrgSCIMConfig(
        organization_id=org.id,
        enabled=True,
        token_hash=_hash_token(raw),
        token_hint=raw[-4:],
    )
    db_session.add(config)
    await db_session.commit()
    return config, raw


# ── Admin SCIM config endpoints ───────────────────────────────────────────────


async def test_get_scim_config_returns_none_when_not_configured(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await scim_client.get(
        "/api/v1/admin/scim",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp.status_code == 200
    assert resp.json() is None


async def test_enable_scim_creates_config_and_returns_token(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await scim_client.post(
        "/api/v1/admin/scim/enable",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "bearer_token" in data
    assert len(data["bearer_token"]) == 64  # 32 bytes hex
    assert data["config"]["enabled"] is True
    assert data["config"]["token_hint"] == data["bearer_token"][-4:]
    assert "scim_base_url" in data["config"]


async def test_enable_scim_requires_owner_role(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    member = await _seed_member(db_session, org)
    resp = await scim_client.post(
        "/api/v1/admin/scim/enable",
        headers={"Authorization": f"Bearer {_bearer(member, org)}"},
    )
    assert resp.status_code == 403


async def test_rotate_scim_token_issues_new_token(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    _, original_token = await _seed_scim_config(db_session, org)

    resp = await scim_client.post(
        "/api/v1/admin/scim/rotate-token",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["bearer_token"] != original_token
    assert data["config"]["token_hint"] == data["bearer_token"][-4:]


async def test_rotate_token_fails_when_not_configured(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await scim_client.post(
        "/api/v1/admin/scim/rotate-token",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp.status_code == 404


async def test_disable_scim_removes_config(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    await _seed_scim_config(db_session, org)

    resp = await scim_client.delete(
        "/api/v1/admin/scim",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp.status_code == 204

    resp2 = await scim_client.get(
        "/api/v1/admin/scim",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp2.json() is None


async def test_disable_scim_returns_404_when_not_configured(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await scim_client.delete(
        "/api/v1/admin/scim",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp.status_code == 404


# ── Domain verification endpoints ─────────────────────────────────────────────


async def test_list_domain_verifications_returns_empty(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await scim_client.get(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_initiate_domain_verification_creates_record(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await scim_client.post(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"domain": "acme.com"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["domain"] == "acme.com"
    assert data["status"] == "pending"
    assert data["txt_record_name"] == "_rudix-challenge.acme.com"
    assert data["txt_record_value"].startswith("rudix-domain-verify=")
    assert len(data["verification_token"]) == 48


async def test_initiate_verification_normalizes_domain(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await scim_client.post(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"domain": "@COMPANY.com"},
    )
    assert resp.status_code == 201
    assert resp.json()["domain"] == "company.com"


async def test_initiate_verification_reuses_record_for_same_domain(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    r1 = await scim_client.post(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"domain": "dup.com"},
    )
    r2 = await scim_client.post(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"domain": "dup.com"},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    # Token should be rotated on re-initiation
    assert r1.json()["verification_token"] != r2.json()["verification_token"]


async def test_delete_domain_verification(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    create_resp = await scim_client.post(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"domain": "delete-me.com"},
    )
    vid = create_resp.json()["id"]

    del_resp = await scim_client.delete(
        f"/api/v1/admin/scim/domains/{vid}",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert del_resp.status_code == 204

    list_resp = await scim_client.get(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert list_resp.json() == []


async def test_check_domain_verification_dns_failure(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    create_resp = await scim_client.post(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"domain": "nxdomain-test-12345.com"},
    )
    vid = create_resp.json()["id"]

    with patch(
        "app.domains.scim.services.domain_verification_service._check_dns_txt",
        return_value=(False, "DNS lookup failed: NXDOMAIN"),
    ):
        check_resp = await scim_client.post(
            f"/api/v1/admin/scim/domains/{vid}/check",
            headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        )

    assert check_resp.status_code == 200
    data = check_resp.json()
    assert data["status"] == "failed"
    assert data["failure_reason"] is not None


async def test_check_domain_verification_dns_success(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    create_resp = await scim_client.post(
        "/api/v1/admin/scim/domains",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"domain": "verified.com"},
    )
    vid = create_resp.json()["id"]

    with patch(
        "app.domains.scim.services.domain_verification_service._check_dns_txt",
        return_value=(True, "DNS TXT record found and verified."),
    ):
        check_resp = await scim_client.post(
            f"/api/v1/admin/scim/domains/{vid}/check",
            headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        )

    assert check_resp.status_code == 200
    data = check_resp.json()
    assert data["status"] == "verified"
    assert data["verified_at"] is not None


# ── SCIM 2.0 protocol endpoints ───────────────────────────────────────────────


async def test_service_provider_config_is_public(
    scim_client: AsyncClient,
) -> None:
    resp = await scim_client.get("/api/v1/scim/v2/ServiceProviderConfig")
    assert resp.status_code == 200
    data = resp.json()
    assert "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig" in data["schemas"]


async def test_scim_users_requires_valid_token(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await scim_client.get(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert resp.status_code == 401


async def test_scim_users_requires_bearer_header(
    scim_client: AsyncClient,
) -> None:
    resp = await scim_client.get("/api/v1/scim/v2/Users")
    assert resp.status_code == 401


async def test_scim_provision_user(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    resp = await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "okta-user-001",
            "userName": "alice@corp.com",
            "displayName": "Alice Example",
            "emails": [{"value": "alice@corp.com", "primary": True, "type": "work"}],
            "active": True,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["userName"] == "alice@corp.com"
    assert data["displayName"] == "Alice Example"
    assert data["active"] is True
    assert data["externalId"] == "okta-user-001"


async def test_scim_provision_user_inactive(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    resp = await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "inactive-001",
            "userName": "inactive@corp.com",
            "active": False,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["active"] is False


async def test_scim_list_users(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    # Provision two users
    for i in range(2):
        await scim_client.post(
            "/api/v1/scim/v2/Users",
            headers={"Authorization": f"Bearer {raw_token}"},
            json={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
                "externalId": f"list-test-{i}",
                "userName": f"listuser{i}@corp.com",
                "active": True,
            },
        )

    resp = await scim_client.get(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalResults"] >= 2
    assert "Resources" in data


async def test_scim_get_user_by_id(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    create_resp = await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "get-test-001",
            "userName": "getuser@corp.com",
            "active": True,
        },
    )
    scim_id = create_resp.json()["externalId"]

    resp = await scim_client.get(
        f"/api/v1/scim/v2/Users/{scim_id}",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["externalId"] == scim_id


async def test_scim_get_user_not_found(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    resp = await scim_client.get(
        "/api/v1/scim/v2/Users/nonexistent-id",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert resp.status_code == 404


async def test_scim_patch_deactivate_user(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    create_resp = await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "patch-deactivate-001",
            "userName": "patch-deactivate@corp.com",
            "active": True,
        },
    )
    scim_id = create_resp.json()["externalId"]

    resp = await scim_client.patch(
        f"/api/v1/scim/v2/Users/{scim_id}",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "active", "value": False}
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False


async def test_scim_delete_user_removes_membership(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    create_resp = await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "delete-001",
            "userName": "todelete@corp.com",
            "active": True,
        },
    )
    assert create_resp.status_code == 201
    scim_id = create_resp.json()["externalId"]

    del_resp = await scim_client.delete(
        f"/api/v1/scim/v2/Users/{scim_id}",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert del_resp.status_code == 204


async def test_scim_delete_nonexistent_user_returns_404(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    resp = await scim_client.delete(
        "/api/v1/scim/v2/Users/no-such-id",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert resp.status_code == 404


async def test_deprovisioned_user_cannot_authenticate(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Users deprovisioned via SCIM DELETE should not be able to make API calls."""
    owner, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    # Provision a user via SCIM
    await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "deprov-test-001",
            "userName": "deprov@corp.com",
            "active": True,
        },
    )

    # Fetch the DB user to get their external_auth_id for token minting
    from sqlalchemy import select
    from app.models.user import User as UserModel
    result = await db_session.execute(
        select(UserModel).where(
            UserModel.email == "deprov@corp.com",
            UserModel.organization_id == org.id,
        )
    )
    scim_user = result.scalar_one()

    # Delete (deprovision) via SCIM
    await scim_client.delete(
        "/api/v1/scim/v2/Users/deprov-test-001",
        headers={"Authorization": f"Bearer {raw_token}"},
    )

    # Attempting to use a token for this user should be rejected
    deprovisioned_token = create_app_access_token(
        subject=scim_user.external_auth_id,
        organization_id=str(org.id),
        email=scim_user.email,
    )
    resp = await scim_client.get(
        "/api/v1/admin/scim",
        headers={"Authorization": f"Bearer {deprovisioned_token}"},
    )
    assert resp.status_code == 401


async def test_scim_filter_users_by_username(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "filter-001",
            "userName": "findme@corp.com",
            "active": True,
        },
    )

    resp = await scim_client.get(
        '/api/v1/scim/v2/Users?filter=userName eq "findme@corp.com"',
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalResults"] >= 1
    assert any(u["userName"] == "findme@corp.com" for u in data["Resources"])


async def test_scim_replace_user_updates_fields(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    _, raw_token = await _seed_scim_config(db_session, org)

    await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "replace-001",
            "userName": "replace@corp.com",
            "displayName": "Old Name",
            "active": True,
        },
    )

    resp = await scim_client.put(
        "/api/v1/scim/v2/Users/replace-001",
        headers={"Authorization": f"Bearer {raw_token}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "replace-001",
            "userName": "replace@corp.com",
            "displayName": "New Name",
            "active": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["displayName"] == "New Name"


# ── Security: cross-org isolation ────────────────────────────────────────────


async def test_scim_token_isolated_to_org(
    scim_client: AsyncClient, db_session: AsyncSession
) -> None:
    """A SCIM token from org A cannot read users provisioned for org B."""
    _, org_a = await _seed_owner(db_session)
    _, org_b = await _seed_owner(db_session)
    _, token_a = await _seed_scim_config(db_session, org_a)
    _, token_b = await _seed_scim_config(db_session, org_b)

    # Provision user in org B
    await scim_client.post(
        "/api/v1/scim/v2/Users",
        headers={"Authorization": f"Bearer {token_b}"},
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "externalId": "org-b-user",
            "userName": "orgb@corp.com",
            "active": True,
        },
    )

    # Token A should NOT see org B's user
    resp = await scim_client.get(
        "/api/v1/scim/v2/Users/org-b-user",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 404
