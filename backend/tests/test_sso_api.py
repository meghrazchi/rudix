"""SSO admin API and auth SSO flow tests (F160)."""

from __future__ import annotations

import base64
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
os.environ.setdefault("APP_AUTH_SECRET", "test-secret-sso")

from app.auth.factory import get_auth_provider
from app.auth.repository import AuthRepository
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.enums import OrganizationRole
from app.models.org_sso_config import OrgSSOConfig
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_repository = AuthRepository()

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def sso_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret-sso"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "app_auth_auto_provision_users", True)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


async def _seed_owner(db_session: AsyncSession) -> tuple[User, Organization]:
    org = Organization(name=f"SSO Org {uuid4().hex[:6]}", slug=f"sso-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"sso-user-{uuid4().hex[:8]}",
        email=f"owner-{uuid4().hex[:6]}@ssotest.com",
        display_name="SSO Owner",
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
        external_auth_id=f"sso-member-{uuid4().hex[:8]}",
        email=f"member-{uuid4().hex[:6]}@ssotest.com",
        display_name="SSO Member",
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


# ── Admin SSO config endpoints ────────────────────────────────────────────────


async def test_get_sso_config_returns_none_when_not_configured(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await sso_client.get(
        "/api/v1/admin/sso", headers={"Authorization": f"Bearer {_bearer(user, org)}"}
    )
    assert resp.status_code == 200
    assert resp.json() is None


async def test_upsert_sso_config_creates_config(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await sso_client.put(
        "/api/v1/admin/sso",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={
            "domain": "acme.com",
            "sso_type": "saml",
            "enabled": False,
            "idp_sso_url": "https://idp.acme.com/sso",
            "idp_entity_id": "https://idp.acme.com",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "acme.com"
    assert data["sso_type"] == "saml"
    assert data["enabled"] is False
    assert "sp_entity_id" in data
    assert "sp_acs_url" in data
    assert data["idp_sso_url"] == "https://idp.acme.com/sso"


async def test_upsert_sso_config_updates_existing(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    auth = {"Authorization": f"Bearer {_bearer(user, org)}"}

    await sso_client.put("/api/v1/admin/sso", headers=auth, json={"domain": "first.com"})
    resp = await sso_client.put(
        "/api/v1/admin/sso",
        headers=auth,
        json={
            "domain": "updated.com",
            "enabled": True,
            "idp_sso_url": "https://idp.updated.com/sso",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["domain"] == "updated.com"
    assert data["enabled"] is True


async def test_upsert_sso_strips_leading_at_from_domain(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await sso_client.put(
        "/api/v1/admin/sso",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"domain": "@cleanme.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["domain"] == "cleanme.com"


async def test_upsert_sso_requires_owner_role(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _user, org = await _seed_owner(db_session)
    member = await _seed_member(db_session, org)
    resp = await sso_client.put(
        "/api/v1/admin/sso",
        headers={"Authorization": f"Bearer {_bearer(member, org)}"},
        json={"domain": "acme.com"},
    )
    assert resp.status_code == 403


async def test_get_sso_config_returns_config_after_upsert(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    auth = {"Authorization": f"Bearer {_bearer(user, org)}"}

    await sso_client.put("/api/v1/admin/sso", headers=auth, json={"domain": "visible.com"})
    resp = await sso_client.get("/api/v1/admin/sso", headers=auth)
    assert resp.status_code == 200
    assert resp.json()["domain"] == "visible.com"


async def test_delete_sso_config(sso_client: AsyncClient, db_session: AsyncSession) -> None:
    user, org = await _seed_owner(db_session)
    auth = {"Authorization": f"Bearer {_bearer(user, org)}"}

    await sso_client.put("/api/v1/admin/sso", headers=auth, json={"domain": "gone.com"})
    resp = await sso_client.delete("/api/v1/admin/sso", headers=auth)
    assert resp.status_code == 204

    resp = await sso_client.get("/api/v1/admin/sso", headers=auth)
    assert resp.json() is None


async def test_delete_sso_config_not_found(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await sso_client.delete(
        "/api/v1/admin/sso",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
    )
    assert resp.status_code == 404


async def test_test_connection_no_inputs_returns_failure(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await sso_client.post(
        "/api/v1/admin/sso/test-connection",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["result"] == "failure"


async def test_test_connection_valid_metadata_xml(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    xml = (
        '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="https://idp.example.com">'
        '<md:IDPSSODescriptor WantAuthnRequestsSigned="false" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        '<md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
        'Location="https://idp.example.com/sso"/>'
        "</md:IDPSSODescriptor>"
        "</md:EntityDescriptor>"
    )
    resp = await sso_client.post(
        "/api/v1/admin/sso/test-connection",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"idp_metadata_xml": xml},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"] == "success"


async def test_test_connection_invalid_xml_returns_failure(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    resp = await sso_client.post(
        "/api/v1/admin/sso/test-connection",
        headers={"Authorization": f"Bearer {_bearer(user, org)}"},
        json={"idp_metadata_xml": "not xml at all <<<"},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False


async def test_test_connection_persists_result_on_existing_config(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    auth = {"Authorization": f"Bearer {_bearer(user, org)}"}
    await sso_client.put("/api/v1/admin/sso", headers=auth, json={"domain": "persist.com"})
    await sso_client.post("/api/v1/admin/sso/test-connection", headers=auth, json={})
    config_resp = await sso_client.get("/api/v1/admin/sso", headers=auth)
    data = config_resp.json()
    assert data["last_test_result"] == "failure"
    assert data["last_test_at"] is not None


# ── Auth SSO flow endpoints ───────────────────────────────────────────────────


async def _seed_enabled_sso_config(
    db_session: AsyncSession, org: Organization, domain: str
) -> OrgSSOConfig:
    config = OrgSSOConfig(
        organization_id=org.id,
        sso_type="saml",
        domain=domain,
        enabled=True,
        idp_sso_url="https://idp.example.com/sso",
        idp_entity_id="https://idp.example.com",
        sp_entity_id=f"https://localhost/auth/sso/{org.id}/metadata",
        sp_acs_url=f"http://localhost:8000/api/v1/auth/sso/{org.id}/callback",
    )
    db_session.add(config)
    await db_session.commit()
    return config


async def test_sso_discover_returns_disabled_for_unknown_domain(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await sso_client.post(
        "/api/v1/auth/sso/discover", json={"email": "user@unknown-domain.com"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sso_enabled"] is False
    assert data["redirect_url"] is None


async def test_sso_discover_returns_redirect_for_enabled_domain(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    await _seed_enabled_sso_config(db_session, org, "enabled-corp.com")

    resp = await sso_client.post(
        "/api/v1/auth/sso/discover", json={"email": "alice@enabled-corp.com"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sso_enabled"] is True
    assert data["sso_type"] == "saml"
    assert data["domain"] == "enabled-corp.com"
    assert data["redirect_url"] is not None
    assert str(org.id) in data["redirect_url"]


async def test_sso_discover_returns_disabled_when_sso_disabled(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    # Create disabled config
    config = OrgSSOConfig(
        organization_id=org.id,
        sso_type="saml",
        domain="disabled-corp.com",
        enabled=False,
        sp_entity_id="https://sp.example.com",
        sp_acs_url="https://sp.example.com/acs",
    )
    db_session.add(config)
    await db_session.commit()

    resp = await sso_client.post(
        "/api/v1/auth/sso/discover", json={"email": "bob@disabled-corp.com"}
    )
    assert resp.status_code == 200
    assert resp.json()["sso_enabled"] is False


async def test_sso_initiate_redirects_to_idp(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    await _seed_enabled_sso_config(db_session, org, "initiate-corp.com")

    resp = await sso_client.get(f"/api/v1/auth/sso/{org.id}/initiate", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "SAMLRequest" in location
    assert "RelayState" in location


async def test_sso_initiate_404_for_unknown_org(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await sso_client.get(f"/api/v1/auth/sso/{uuid4()}/initiate", follow_redirects=False)
    assert resp.status_code == 404


async def test_sso_sp_metadata_returns_xml(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    await _seed_enabled_sso_config(db_session, org, "meta-corp.com")

    resp = await sso_client.get(f"/api/v1/auth/sso/{org.id}/metadata")
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert "EntityDescriptor" in resp.text
    assert "AssertionConsumerService" in resp.text


async def test_sso_sp_metadata_404_for_unknown_org(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await sso_client.get(f"/api/v1/auth/sso/{uuid4()}/metadata")
    assert resp.status_code == 404


async def test_sso_callback_provisions_user_and_issues_tokens(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    await _seed_enabled_sso_config(db_session, org, "newuser-corp.com")

    email = f"newuser-{uuid4().hex[:6]}@newuser-corp.com"
    saml_xml = (
        f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">'
        f'<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
        f"<saml:Subject><saml:NameID>{email}</saml:NameID></saml:Subject>"
        f"<saml:AttributeStatement>"
        f'<saml:Attribute Name="email">'
        f"<saml:AttributeValue>{email}</saml:AttributeValue>"
        f"</saml:Attribute>"
        f"</saml:AttributeStatement>"
        f"</saml:Assertion>"
        f"</samlp:Response>"
    )
    saml_b64 = base64.b64encode(saml_xml.encode()).decode()

    resp = await sso_client.post(
        f"/api/v1/auth/sso/{org.id}/callback",
        data={"SAMLResponse": saml_b64, "RelayState": ""},
    )
    assert resp.status_code == 302
    assert "access_token=" in resp.headers["location"]
    assert "session_id=" in resp.headers["location"]
    assert resp.cookies.get("rudix_refresh_token")


async def test_sso_callback_logs_in_existing_user(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_owner(db_session)
    await _seed_enabled_sso_config(db_session, org, "existing-corp.com")

    saml_xml = (
        f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">'
        f'<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
        f"<saml:Subject><saml:NameID>{user.email}</saml:NameID></saml:Subject>"
        f"</saml:Assertion>"
        f"</samlp:Response>"
    )
    saml_b64 = base64.b64encode(saml_xml.encode()).decode()

    resp = await sso_client.post(
        f"/api/v1/auth/sso/{org.id}/callback",
        data={"SAMLResponse": saml_b64},
    )
    assert resp.status_code == 302
    assert "access_token=" in resp.headers["location"]
    assert resp.cookies.get("rudix_refresh_token")


async def test_sso_callback_400_for_invalid_saml(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    await _seed_enabled_sso_config(db_session, org, "bad-saml.com")

    resp = await sso_client.post(
        f"/api/v1/auth/sso/{org.id}/callback",
        data={"SAMLResponse": "not-valid-base64!!!"},
    )
    assert resp.status_code == 400


async def test_sso_callback_400_for_missing_saml_response(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    await _seed_enabled_sso_config(db_session, org, "missing-sr.com")

    resp = await sso_client.post(f"/api/v1/auth/sso/{org.id}/callback", data={})
    assert resp.status_code == 400


async def test_sso_callback_404_for_disabled_sso(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    _, org = await _seed_owner(db_session)
    config = OrgSSOConfig(
        organization_id=org.id,
        sso_type="saml",
        domain="off-corp.com",
        enabled=False,
        sp_entity_id="https://sp.example.com",
        sp_acs_url="https://sp.example.com/acs",
    )
    db_session.add(config)
    await db_session.commit()

    resp = await sso_client.post(
        f"/api/v1/auth/sso/{org.id}/callback",
        data={"SAMLResponse": base64.b64encode(b"<x/>").decode()},
    )
    assert resp.status_code == 404


# ── Refresh token works for SSO sessions ─────────────────────────────────────


async def test_sso_session_refresh_token_works(
    sso_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Tokens issued by SSO callback must be refreshable via /auth/token/refresh."""
    user, org = await _seed_owner(db_session)
    await _seed_enabled_sso_config(db_session, org, "refresh-corp.com")

    saml_xml = (
        f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">'
        f'<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
        f"<saml:Subject><saml:NameID>{user.email}</saml:NameID></saml:Subject>"
        f"</saml:Assertion>"
        f"</samlp:Response>"
    )
    saml_b64 = base64.b64encode(saml_xml.encode()).decode()

    login_resp = await sso_client.post(
        f"/api/v1/auth/sso/{org.id}/callback",
        data={"SAMLResponse": saml_b64},
    )
    assert login_resp.status_code == 302

    # The refresh token is in an HTTP-only cookie
    refresh_token = login_resp.cookies.get("rudix_refresh_token")
    assert refresh_token is not None

    refresh_resp = await sso_client.post(
        "/api/v1/auth/token/refresh",
        cookies={"rudix_refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    assert data["access_token"]
    assert data["expires_in"] > 0
