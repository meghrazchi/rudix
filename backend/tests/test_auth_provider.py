import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app")
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

from app.auth.errors import AuthenticationError
from app.auth.factory import get_auth_provider
from app.auth.providers.app_provider import AppAuthProvider
from app.auth.providers.jwt_jwks_provider import JwtJwksAuthProvider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


def _auth_request(token: str, organization_id: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"authorization", f"Bearer {token}".encode())]
    if organization_id is not None:
        headers.append((b"x-organization-id", organization_id.encode()))
    return Request({"type": "http", "headers": headers})


def _generate_rsa_signing_material(*, kid: str) -> tuple[rsa.RSAPrivateKey, dict[str, str]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk["kid"] = kid
    public_jwk["alg"] = "RS256"
    public_jwk["use"] = "sig"
    return private_key, public_jwk


def _create_jwt(
    *,
    private_key: rsa.RSAPrivateKey,
    kid: str,
    subject: str,
    issuer: str,
    audience: str,
    expires_in_seconds: int,
    email: str | None = None,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": subject,
        "iss": issuer,
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    if email is not None:
        payload["email"] = email
    return jwt.encode(
        payload,
        key=private_key,
        algorithm="RS256",
        headers={"kid": kid, "typ": "JWT"},
    )


@pytest.mark.asyncio
async def test_app_provider_authenticates_valid_token(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")

    organization = Organization(name="Auth Org", slug=f"auth-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id="auth-user-1",
        email="auth-user-1@example.com",
        display_name="Auth User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    provider = AppAuthProvider()
    principal = await provider.authenticate(_auth_request(token, str(organization.id)), db_session)

    assert principal.user_id == str(user.id)
    assert principal.organization_id == str(organization.id)
    assert principal.roles == [OrganizationRole.member.value]
    assert principal.auth_provider == "app"


@pytest.mark.asyncio
async def test_app_provider_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")

    provider = AppAuthProvider()
    with pytest.raises(AuthenticationError):
        await provider.authenticate(_auth_request("invalid.token.value"), db_session)


def test_provider_selection_is_environment_driven(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    get_auth_provider.cache_clear()
    assert isinstance(get_auth_provider(), AppAuthProvider)

    monkeypatch.setattr(settings, "auth_provider", AuthProvider.clerk)
    get_auth_provider.cache_clear()
    assert isinstance(get_auth_provider(), JwtJwksAuthProvider)


@pytest.mark.asyncio
async def test_clerk_provider_authenticates_valid_token(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.clerk)
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.example.com/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_jwt_issuer", "https://clerk.example.com")
    monkeypatch.setattr(settings, "clerk_jwt_audience", "rudix-api")
    monkeypatch.setattr(settings, "auth_jwks_cache_ttl_seconds", 300)

    organization = Organization(name="Clerk Org", slug=f"clerk-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id="user_clerk_1",
        email="clerk-user-1@example.com",
        display_name="Clerk User",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()

    provider = JwtJwksAuthProvider()
    private_key, jwk = _generate_rsa_signing_material(kid="clerk-kid-1")
    token = _create_jwt(
        private_key=private_key,
        kid="clerk-kid-1",
        subject=user.external_auth_id,
        issuer="https://clerk.example.com",
        audience="rudix-api",
        expires_in_seconds=600,
        email="token-email@example.com",
    )

    async def fake_fetch_jwks(_: str) -> dict[str, object]:
        return {"keys": [jwk]}

    monkeypatch.setattr(provider, "_fetch_jwks", fake_fetch_jwks)
    principal = await provider.authenticate(_auth_request(token, str(organization.id)), db_session)

    assert principal.user_id == str(user.id)
    assert principal.organization_id == str(organization.id)
    assert principal.roles == [OrganizationRole.member.value]
    assert principal.auth_provider == "clerk"
    assert principal.email == "token-email@example.com"


@pytest.mark.asyncio
async def test_clerk_provider_rejects_expired_token(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.clerk)
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.example.com/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_jwt_issuer", "https://clerk.example.com")
    monkeypatch.setattr(settings, "clerk_jwt_audience", "rudix-api")

    organization = Organization(name="Expired Org", slug=f"expired-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id="user_clerk_expired",
        email="clerk-user-expired@example.com",
        display_name="Clerk User Expired",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()

    provider = JwtJwksAuthProvider()
    private_key, jwk = _generate_rsa_signing_material(kid="clerk-kid-expired")
    token = _create_jwt(
        private_key=private_key,
        kid="clerk-kid-expired",
        subject=user.external_auth_id,
        issuer="https://clerk.example.com",
        audience="rudix-api",
        expires_in_seconds=-30,
    )

    async def fake_fetch_jwks(_: str) -> dict[str, object]:
        return {"keys": [jwk]}

    monkeypatch.setattr(provider, "_fetch_jwks", fake_fetch_jwks)
    with pytest.raises(AuthenticationError, match="Token has expired"):
        await provider.authenticate(_auth_request(token, str(organization.id)), db_session)


@pytest.mark.asyncio
async def test_clerk_provider_rejects_wrong_issuer_or_audience(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.clerk)
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.example.com/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_jwt_issuer", "https://clerk.example.com")
    monkeypatch.setattr(settings, "clerk_jwt_audience", "rudix-api")

    organization = Organization(name="Issuer Org", slug=f"issuer-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id="user_clerk_issuer",
        email="clerk-user-issuer@example.com",
        display_name="Clerk User Issuer",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()

    provider = JwtJwksAuthProvider()
    private_key, jwk = _generate_rsa_signing_material(kid="clerk-kid-issuer")

    async def fake_fetch_jwks(_: str) -> dict[str, object]:
        return {"keys": [jwk]}

    monkeypatch.setattr(provider, "_fetch_jwks", fake_fetch_jwks)

    wrong_issuer_token = _create_jwt(
        private_key=private_key,
        kid="clerk-kid-issuer",
        subject=user.external_auth_id,
        issuer="https://wrong-issuer.example.com",
        audience="rudix-api",
        expires_in_seconds=600,
    )
    with pytest.raises(AuthenticationError, match="Invalid token issuer"):
        await provider.authenticate(_auth_request(wrong_issuer_token, str(organization.id)), db_session)

    wrong_audience_token = _create_jwt(
        private_key=private_key,
        kid="clerk-kid-issuer",
        subject=user.external_auth_id,
        issuer="https://clerk.example.com",
        audience="other-audience",
        expires_in_seconds=600,
    )
    with pytest.raises(AuthenticationError, match="Invalid token audience"):
        await provider.authenticate(_auth_request(wrong_audience_token, str(organization.id)), db_session)


@pytest.mark.asyncio
async def test_clerk_provider_refreshes_jwks_when_kid_changes(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> None:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.clerk)
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.example.com/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_jwt_issuer", "https://clerk.example.com")
    monkeypatch.setattr(settings, "clerk_jwt_audience", "rudix-api")
    monkeypatch.setattr(settings, "auth_jwks_cache_ttl_seconds", 300)

    organization = Organization(name="Rotation Org", slug=f"rotation-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id="user_clerk_rotation",
        email="clerk-user-rotation@example.com",
        display_name="Clerk User Rotation",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()

    provider = JwtJwksAuthProvider()
    old_private_key, old_jwk = _generate_rsa_signing_material(kid="clerk-old-kid")
    new_private_key, new_jwk = _generate_rsa_signing_material(kid="clerk-new-kid")
    del old_private_key

    token = _create_jwt(
        private_key=new_private_key,
        kid="clerk-new-kid",
        subject=user.external_auth_id,
        issuer="https://clerk.example.com",
        audience="rudix-api",
        expires_in_seconds=600,
    )

    fetch_count = 0

    async def fake_fetch_jwks(_: str) -> dict[str, object]:
        nonlocal fetch_count
        fetch_count += 1
        if fetch_count == 1:
            return {"keys": [old_jwk]}
        return {"keys": [new_jwk]}

    monkeypatch.setattr(provider, "_fetch_jwks", fake_fetch_jwks)
    principal = await provider.authenticate(_auth_request(token, str(organization.id)), db_session)

    assert principal.user_id == str(user.id)
    assert fetch_count == 2
