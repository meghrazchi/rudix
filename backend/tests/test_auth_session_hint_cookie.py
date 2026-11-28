"""Session-hint cookie and cookie Origin check on the auth routes (R07-09)."""

from __future__ import annotations

import base64
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.factory import get_auth_provider
from app.auth.passwords import PasswordHashConfig, build_password_hasher, hash_password
from app.core.config import AuthProvider, Environment, settings
from app.core.metrics_auth_session import AUTH_CSRF_ORIGIN_REJECTIONS_TOTAL
from app.core.settings.auth import validate_auth_cookies
from app.db.session import get_db_session
from app.main import app
from app.models.enums import OrganizationRole
from app.models.org_sso_config import OrgSSOConfig
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_HINT = "rudix_session_hint"
_REFRESH = "rudix_refresh_token"
_password_hasher = build_password_hasher(
    PasswordHashConfig(
        memory_cost=65536, time_cost=3, parallelism=1, hash_length=32, salt_length=16
    )
)


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "app_auth_auto_provision_users", False)
    monkeypatch.setattr(settings, "app_auth_cookie_secure", False)
    monkeypatch.setattr(settings, "app_auth_cookie_same_site", "lax")
    monkeypatch.setattr(settings, "app_auth_cookie_domain", None)
    monkeypatch.setattr(settings, "app_auth_session_hint_cookie_enabled", False)
    monkeypatch.setattr(settings, "app_auth_session_hint_cookie_name", _HINT)
    monkeypatch.setattr(settings, "app_auth_session_hint_cookie_domain", None)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    app.dependency_overrides.clear()


def _enable_hint(monkeypatch: pytest.MonkeyPatch, *, domain: str | None = None) -> None:
    monkeypatch.setattr(settings, "app_auth_session_hint_cookie_enabled", True)
    monkeypatch.setattr(settings, "app_auth_session_hint_cookie_domain", domain)


async def _seed_user(db_session: AsyncSession) -> tuple[User, Organization]:
    org = Organization(name="Hint Org", slug=f"hint-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"hint-{uuid4().hex[:8]}",
        email=f"hint-{uuid4().hex[:8]}@example.com",
        display_name="Hint User",
        hashed_password=hash_password("password123", _password_hasher),
        password_state="active",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=OrganizationRole.member.value
        )
    )
    await db_session.commit()
    return user, org


def _cookies(response: Response) -> dict[str, tuple[str, frozenset[str]]]:
    """Map cookie name -> (value, lower-cased attribute set) for every Set-Cookie header."""
    parsed: dict[str, tuple[str, frozenset[str]]] = {}
    for header in response.headers.get_list("set-cookie"):
        first, *attributes = (part.strip() for part in header.split(";"))
        name, _, value = first.partition("=")
        parsed[name] = (value.strip('"'), frozenset(a.lower() for a in attributes if a))
    return parsed


def _is_cleared(attributes: frozenset[str]) -> bool:
    return "max-age=0" in attributes or any(a.startswith("expires=") for a in attributes)


async def _login(client: AsyncClient, user: User) -> Response:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "password123"}
    )
    assert response.status_code == 200
    return response


def _saml_b64(email: str) -> str:
    xml = (
        '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol">'
        '<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion">'
        f"<saml:Subject><saml:NameID>{email}</saml:NameID></saml:Subject>"
        "</saml:Assertion></samlp:Response>"
    )
    return base64.b64encode(xml.encode()).decode()


async def _seed_sso(db_session: AsyncSession, org: Organization) -> None:
    db_session.add(
        OrgSSOConfig(
            organization_id=org.id,
            sso_type="saml",
            domain=f"hint-{uuid4().hex[:6]}.com",
            enabled=True,
            idp_sso_url="https://idp.example.com/sso",
            idp_entity_id="https://idp.example.com",
            sp_entity_id=f"https://localhost/auth/sso/{org.id}/metadata",
            sp_acs_url=f"http://localhost:8000/api/v1/auth/sso/{org.id}/callback",
        )
    )
    await db_session.commit()


# ── Disabled (default): headers identical to today ──────────────────────────────


async def test_disabled_login_refresh_logout_set_only_the_refresh_cookie(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, _ = await _seed_user(db_session)
    login = await _login(client, user)
    assert len(login.headers.get_list("set-cookie")) == 1
    value, attributes = _cookies(login)[_REFRESH]
    assert attributes == {"httponly", "max-age=1209600", "path=/api/v1/auth", "samesite=lax"}

    refresh = await client.post("/api/v1/auth/token/refresh", cookies={_REFRESH: value})
    assert refresh.status_code == 200
    assert list(_cookies(refresh)) == [_REFRESH]

    failed = await client.post("/api/v1/auth/token/refresh", cookies={_REFRESH: "bad"})
    assert failed.status_code == 401
    assert failed.headers.get_list("set-cookie") == []

    logout = await client.post("/api/v1/auth/logout", cookies={_REFRESH: value})
    assert logout.status_code == 200
    assert list(_cookies(logout)) == [_REFRESH]


# ── Enabled: set with the refresh cookie, exact flags ───────────────────────────


async def test_enabled_login_sets_hint_with_exact_flags(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_hint(monkeypatch, domain=".example.com")
    monkeypatch.setattr(settings, "app_auth_cookie_secure", True)
    user, _ = await _seed_user(db_session)

    cookies = _cookies(await _login(client, user))

    hint_value, hint_attributes = cookies[_HINT]
    assert hint_value == "1"
    assert hint_attributes == {
        "domain=.example.com",
        "httponly",
        "max-age=1209600",
        "path=/",
        "samesite=lax",
        "secure",
    }
    # The refresh cookie keeps its attributes: host-only, auth path.
    _, refresh_attributes = cookies[_REFRESH]
    assert refresh_attributes == {
        "httponly",
        "max-age=1209600",
        "path=/api/v1/auth",
        "samesite=lax",
        "secure",
    }


async def test_enabled_hint_follows_same_site_and_custom_name(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_hint(monkeypatch)
    monkeypatch.setattr(settings, "app_auth_session_hint_cookie_name", "custom_hint")
    monkeypatch.setattr(settings, "app_auth_cookie_same_site", "strict")
    user, _ = await _seed_user(db_session)

    cookies = _cookies(await _login(client, user))

    assert _HINT not in cookies
    _, attributes = cookies["custom_hint"]
    assert "samesite=strict" in attributes
    assert not any(a.startswith("domain=") for a in attributes)
    assert "secure" not in attributes


async def test_enabled_refresh_sets_hint_and_logout_clears_it(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_hint(monkeypatch)
    user, _ = await _seed_user(db_session)
    refresh_token = _cookies(await _login(client, user))[_REFRESH][0]

    refresh = await client.post("/api/v1/auth/token/refresh", cookies={_REFRESH: refresh_token})
    assert refresh.status_code == 200
    rotated = _cookies(refresh)
    assert rotated[_HINT][0] == "1"
    assert not _is_cleared(rotated[_HINT][1])

    logout = await client.post("/api/v1/auth/logout", cookies={_REFRESH: rotated[_REFRESH][0]})
    assert logout.status_code == 200
    cleared = _cookies(logout)
    assert _is_cleared(cleared[_HINT][1])
    assert "path=/" in cleared[_HINT][1]
    assert _is_cleared(cleared[_REFRESH][1])


async def test_enabled_logout_all_clears_hint(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_hint(monkeypatch, domain=".example.com")
    user, _ = await _seed_user(db_session)
    access_token = (await _login(client, user)).json()["access_token"]

    response = await client.post(
        "/api/v1/auth/logout-all", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    _, attributes = _cookies(response)[_HINT]
    assert _is_cleared(attributes)
    assert "domain=.example.com" in attributes


@pytest.mark.parametrize("refresh_cookie", [None, "not-a-jwt"])
async def test_enabled_refresh_401_clears_hint_only(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    refresh_cookie: str | None,
) -> None:
    _enable_hint(monkeypatch)
    cookies = {_REFRESH: refresh_cookie} if refresh_cookie else None

    response = await client.post("/api/v1/auth/token/refresh", cookies=cookies)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    parsed = _cookies(response)
    assert list(parsed) == [_HINT]
    assert _is_cleared(parsed[_HINT][1])


async def test_enabled_refresh_revoked_and_reused_clear_hint(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_hint(monkeypatch)
    user, _ = await _seed_user(db_session)
    first = _cookies(await _login(client, user))[_REFRESH][0]
    rotated = await client.post("/api/v1/auth/token/refresh", cookies={_REFRESH: first})
    assert rotated.status_code == 200

    reused = await client.post("/api/v1/auth/token/refresh", cookies={_REFRESH: first})
    assert reused.status_code == 403
    assert _is_cleared(_cookies(reused)[_HINT][1])

    revoked = await client.post(
        "/api/v1/auth/token/refresh", cookies={_REFRESH: _cookies(rotated)[_REFRESH][0]}
    )
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "Refresh session is not valid"
    assert _is_cleared(_cookies(revoked)[_HINT][1])


async def test_enabled_refresh_rate_limit_or_provider_errors_keep_hint(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_hint(monkeypatch)
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.clerk)

    response = await client.post("/api/v1/auth/token/refresh")

    assert response.status_code == 503
    assert response.headers.get_list("set-cookie") == []


async def test_enabled_sso_json_and_redirect_set_hint(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_hint(monkeypatch)
    user, org = await _seed_user(db_session)
    await _seed_sso(db_session, org)

    as_json = await client.post(
        f"/api/v1/auth/sso/{org.id}/callback",
        data={"SAMLResponse": _saml_b64(user.email)},
        headers={"accept": "application/json"},
    )
    assert as_json.status_code == 200
    assert _cookies(as_json)[_HINT][0] == "1"

    redirect = await client.post(
        f"/api/v1/auth/sso/{org.id}/callback",
        data={"SAMLResponse": _saml_b64(user.email)},
    )
    assert redirect.status_code == 302
    cookies = _cookies(redirect)
    assert cookies[_HINT][0] == "1"
    assert {"path=/", "httponly"} <= cookies[_HINT][1]
    assert _REFRESH in cookies


# ── Settings validation ─────────────────────────────────────────────────────────


def test_validation_strips_hint_domain_and_keeps_production_secure_rule() -> None:
    candidate = settings.model_copy(
        update={
            "app_auth_session_hint_cookie_domain": "  .getrudix.com  ",
            "app_auth_cookie_secure": None,
            "app_auth_cookie_same_site": "lax",
            "environment": Environment.production,
        }
    )
    validate_auth_cookies(candidate)
    assert candidate.app_auth_session_hint_cookie_domain == ".getrudix.com"
    assert candidate.app_auth_cookie_secure is True

    blank = settings.model_copy(update={"app_auth_session_hint_cookie_domain": "   "})
    validate_auth_cookies(blank)
    assert blank.app_auth_session_hint_cookie_domain is None

    insecure = settings.model_copy(
        update={"app_auth_cookie_secure": False, "environment": Environment.production}
    )
    with pytest.raises(ValueError, match="production"):
        validate_auth_cookies(insecure)


def test_hint_cookie_settings_defaults_keep_todays_behaviour() -> None:
    from app.core.settings.auth import AuthSettings

    defaults = AuthSettings()
    assert defaults.app_auth_session_hint_cookie_enabled is False
    assert defaults.app_auth_session_hint_cookie_name == "rudix_session_hint"
    assert defaults.app_auth_session_hint_cookie_domain is None


# ── Origin check when SameSite=None ─────────────────────────────────────────────


def _same_site_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_auth_cookie_same_site", "none")
    monkeypatch.setattr(settings, "app_auth_cookie_secure", True)
    monkeypatch.setattr(settings, "cors_origins", ["https://app.example.com/"])


def _rejections(endpoint: str, reason: str) -> float:
    return AUTH_CSRF_ORIGIN_REJECTIONS_TOTAL.labels(endpoint=endpoint, reason=reason)._value.get()


@pytest.mark.parametrize("path", ["/api/v1/auth/token/refresh", "/api/v1/auth/logout"])
@pytest.mark.parametrize(
    ("origin", "reason"),
    [(None, "missing"), ("https://evil.example.net", "foreign"), ("null", "foreign")],
)
async def test_same_site_none_rejects_missing_or_foreign_origin(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    origin: str | None,
    reason: str,
) -> None:
    _same_site_none(monkeypatch)
    monkeypatch.setattr(settings, "metrics_enabled", True)
    _enable_hint(monkeypatch)
    endpoint = "refresh" if path.endswith("/refresh") else "logout"
    before = _rejections(endpoint, reason)
    headers = {"origin": origin} if origin else {}

    response = await client.post(path, headers=headers, cookies={_REFRESH: "token"})

    assert response.status_code == 403
    body = response.json()
    assert body["error"]["code"] == "csrf_origin_rejected"
    assert body["error"]["message"] == "Request origin is not allowed"
    assert "token" not in response.text
    # A rejected cross-site request must not touch the victim's cookies.
    assert response.headers.get_list("set-cookie") == []
    assert _rejections(endpoint, reason) == before + 1


async def test_same_site_none_allows_listed_origin(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _same_site_none(monkeypatch)
    user, _ = await _seed_user(db_session)
    refresh_token = _cookies(await _login(client, user))[_REFRESH][0]
    origin = {"origin": "HTTPS://app.example.com"}

    refresh = await client.post(
        "/api/v1/auth/token/refresh", headers=origin, cookies={_REFRESH: refresh_token}
    )
    assert refresh.status_code == 200

    logout = await client.post(
        "/api/v1/auth/logout", headers=origin, cookies={_REFRESH: _cookies(refresh)[_REFRESH][0]}
    )
    assert logout.status_code == 200


@pytest.mark.parametrize("same_site", ["lax", "strict"])
async def test_lax_and_strict_do_not_check_origin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, same_site: str
) -> None:
    monkeypatch.setattr(settings, "app_auth_cookie_same_site", same_site)
    monkeypatch.setattr(settings, "cors_origins", ["https://app.example.com"])
    foreign = {"origin": "https://evil.example.net"}

    logout = await client.post("/api/v1/auth/logout", headers=foreign)
    refresh = await client.post("/api/v1/auth/token/refresh", headers=foreign)

    assert logout.status_code == 200
    assert refresh.status_code == 401
