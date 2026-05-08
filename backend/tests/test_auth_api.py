import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
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


@pytest_asyncio.fixture
async def auth_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
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
) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Primary Org", slug=f"primary-org-{uuid4().hex[:8]}")
    secondary_org = Organization(name="Secondary Org", slug=f"secondary-org-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, secondary_org])
    await db_session.flush()

    user = User(
        organization_id=primary_org.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Auth API User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=primary_org.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, primary_org, secondary_org


def _auth_headers(*, token: str, organization_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if organization_id is not None:
        headers["X-Organization-ID"] = organization_id
    return headers


@pytest.mark.asyncio
async def test_protected_route_rejects_missing_credentials(auth_client: AsyncClient) -> None:
    response = await auth_client.get("/api/v1/pipeline/steps")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


@pytest.mark.asyncio
async def test_protected_route_rejects_invalid_credentials(auth_client: AsyncClient) -> None:
    response = await auth_client.get(
        "/api/v1/pipeline/steps",
        headers={"Authorization": "Bearer not-a-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token format"


@pytest.mark.asyncio
async def test_protected_route_rejects_expired_token(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=-5,
    )

    response = await auth_client.get(
        "/api/v1/pipeline/steps",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token has expired"


@pytest.mark.asyncio
async def test_protected_route_allows_valid_authenticated_request(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.get(
        "/api/v1/pipeline/steps",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    assert "steps" in response.json()


@pytest.mark.asyncio
async def test_authorization_rejects_cross_organization_access(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, primary_org, secondary_org = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.get(
        "/api/v1/pipeline/steps",
        headers=_auth_headers(token=token, organization_id=str(secondary_org.id)),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-organization access is not allowed"


@pytest.mark.asyncio
async def test_authorization_rejects_insufficient_role(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, _ = await _seed_principal(db_session, role=OrganizationRole.viewer)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.post(
        "/api/v1/documents/upload-url",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "filename": "sample.pdf",
            "file_type": "pdf",
            "file_size_bytes": 1024,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role for requested operation"


@pytest.mark.asyncio
async def test_authorization_allows_same_organization_with_valid_role(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.post(
        "/api/v1/documents/upload-url",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "filename": "sample.pdf",
            "file_type": "pdf",
            "file_size_bytes": 1024,
        },
    )

    # Handler is scaffold-only; successful authz reaches route and returns 501.
    assert response.status_code == 501
