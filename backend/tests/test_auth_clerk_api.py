import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

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
os.environ.setdefault("AUTH_PROVIDER", "clerk")
os.environ.setdefault("CLERK_JWKS_URL", "https://clerk.example.com/.well-known/jwks.json")
os.environ.setdefault("CLERK_JWT_ISSUER", "https://clerk.example.com")
os.environ.setdefault("CLERK_JWT_AUDIENCE", "rudix-api")

from app.auth.factory import get_auth_provider
from app.auth.providers.jwt_jwks_provider import JwtJwksAuthProvider
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


def _auth_headers(*, token: str, organization_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if organization_id is not None:
        headers["X-Organization-ID"] = organization_id
    return headers


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


async def _seed_principal(db_session: AsyncSession) -> tuple[User, Organization]:
    organization = Organization(name="Clerk API Org", slug=f"clerk-api-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id="user_clerk_api",
        email="clerk-api-user@example.com",
        display_name="Clerk API User",
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
    return user, organization


@pytest_asyncio.fixture
async def clerk_auth_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.clerk)
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://clerk.example.com/.well-known/jwks.json")
    monkeypatch.setattr(settings, "clerk_jwt_issuer", "https://clerk.example.com")
    monkeypatch.setattr(settings, "clerk_jwt_audience", "rudix-api")
    monkeypatch.setattr(settings, "auth_jwks_cache_ttl_seconds", 300)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


@pytest.mark.asyncio
async def test_clerk_protected_route_rejects_missing_credentials(clerk_auth_client: AsyncClient) -> None:
    response = await clerk_auth_client.get("/api/v1/pipeline/steps")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


@pytest.mark.asyncio
async def test_clerk_protected_route_allows_valid_token(
    monkeypatch: pytest.MonkeyPatch,
    clerk_auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    private_key, jwk = _generate_rsa_signing_material(kid="clerk-api-kid-1")
    token = _create_jwt(
        private_key=private_key,
        kid="clerk-api-kid-1",
        subject=user.external_auth_id,
        issuer="https://clerk.example.com",
        audience="rudix-api",
        expires_in_seconds=600,
    )

    async def fake_fetch_jwks(_: JwtJwksAuthProvider, __: str) -> dict[str, object]:
        return {"keys": [jwk]}

    monkeypatch.setattr(JwtJwksAuthProvider, "_fetch_jwks", fake_fetch_jwks)

    response = await clerk_auth_client.get(
        "/api/v1/pipeline/steps",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    assert "steps" in response.json()


@pytest.mark.asyncio
async def test_clerk_protected_route_rejects_expired_token(
    monkeypatch: pytest.MonkeyPatch,
    clerk_auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    private_key, jwk = _generate_rsa_signing_material(kid="clerk-api-kid-expired")
    token = _create_jwt(
        private_key=private_key,
        kid="clerk-api-kid-expired",
        subject=user.external_auth_id,
        issuer="https://clerk.example.com",
        audience="rudix-api",
        expires_in_seconds=-10,
    )

    async def fake_fetch_jwks(_: JwtJwksAuthProvider, __: str) -> dict[str, object]:
        return {"keys": [jwk]}

    monkeypatch.setattr(JwtJwksAuthProvider, "_fetch_jwks", fake_fetch_jwks)

    response = await clerk_auth_client.get(
        "/api/v1/pipeline/steps",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"


@pytest.mark.asyncio
async def test_clerk_protected_route_rejects_wrong_issuer_or_audience(
    monkeypatch: pytest.MonkeyPatch,
    clerk_auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_principal(db_session)
    private_key, jwk = _generate_rsa_signing_material(kid="clerk-api-kid-issuer")

    async def fake_fetch_jwks(_: JwtJwksAuthProvider, __: str) -> dict[str, object]:
        return {"keys": [jwk]}

    monkeypatch.setattr(JwtJwksAuthProvider, "_fetch_jwks", fake_fetch_jwks)

    wrong_issuer = _create_jwt(
        private_key=private_key,
        kid="clerk-api-kid-issuer",
        subject=user.external_auth_id,
        issuer="https://wrong-issuer.example.com",
        audience="rudix-api",
        expires_in_seconds=600,
    )
    issuer_response = await clerk_auth_client.get(
        "/api/v1/pipeline/steps",
        headers=_auth_headers(token=wrong_issuer, organization_id=str(org.id)),
    )
    assert issuer_response.status_code == 401
    assert issuer_response.json()["detail"] == "Invalid token issuer"

    wrong_audience = _create_jwt(
        private_key=private_key,
        kid="clerk-api-kid-issuer",
        subject=user.external_auth_id,
        issuer="https://clerk.example.com",
        audience="unexpected-audience",
        expires_in_seconds=600,
    )
    audience_response = await clerk_auth_client.get(
        "/api/v1/pipeline/steps",
        headers=_auth_headers(token=wrong_audience, organization_id=str(org.id)),
    )
    assert audience_response.status_code == 401
    assert audience_response.json()["detail"] == "Invalid token audience"
