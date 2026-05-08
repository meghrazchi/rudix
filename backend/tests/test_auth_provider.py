import os
from uuid import uuid4

import pytest
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
