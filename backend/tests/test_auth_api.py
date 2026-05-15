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
from app.auth.repository import AuthRepository
from app.auth.token_codec import create_app_access_token, decode_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.repositories.evaluations import EvaluationRepository

_repository = AuthRepository()


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


async def _seed_user_for_org(
    db_session: AsyncSession,
    *,
    organization: Organization,
    role: OrganizationRole = OrganizationRole.member,
) -> User:
    user = User(
        organization_id=organization.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Org User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user


async def _seed_document(
    db_session: AsyncSession,
    *,
    organization: Organization,
    uploader: User,
    filename: str,
) -> Document:
    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename=filename,
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{filename}",
        status="uploaded",
    )
    db_session.add(document)
    await db_session.commit()
    await db_session.refresh(document)
    return document


def _auth_headers(*, token: str, organization_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if organization_id is not None:
        headers["X-Organization-ID"] = organization_id
    return headers


def _extract_refresh_cookie(response) -> str:
    set_cookie = response.headers.get("set-cookie")
    assert set_cookie is not None
    prefix = "rudix_refresh_token="
    assert prefix in set_cookie
    return set_cookie.split(prefix, maxsplit=1)[1].split(";", maxsplit=1)[0]


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


@pytest.mark.asyncio
async def test_document_guard_hides_cross_organization_document(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, primary_org, secondary_org = await _seed_principal(db_session, role=OrganizationRole.member)
    secondary_user = await _seed_user_for_org(db_session, organization=secondary_org)
    foreign_document = await _seed_document(
        db_session,
        organization=secondary_org,
        uploader=secondary_user,
        filename="foreign.pdf",
    )

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.get(
        f"/api/v1/documents/{foreign_document.id}",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_document_guard_allows_same_organization_document(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    document = await _seed_document(db_session, organization=org, uploader=user, filename="same-org.pdf")
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.get(
        f"/api/v1/documents/{document.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    assert response.json()["document_id"] == str(document.id)


@pytest.mark.asyncio
async def test_chat_document_guard_rejects_cross_organization_document_ids(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, primary_org, secondary_org = await _seed_principal(db_session, role=OrganizationRole.member)
    secondary_user = await _seed_user_for_org(db_session, organization=secondary_org)
    foreign_document = await _seed_document(
        db_session,
        organization=secondary_org,
        uploader=secondary_user,
        filename="chat-foreign.pdf",
    )

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.post(
        "/api/v1/chat/sessions/session-1/messages",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
        json={
            "message": "hello",
            "document_ids": [str(foreign_document.id)],
            "stream": False,
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_evaluation_document_guard_rejects_cross_organization_document_id(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    evaluation_repository = EvaluationRepository()
    user, primary_org, secondary_org = await _seed_principal(db_session, role=OrganizationRole.admin)
    secondary_user = await _seed_user_for_org(db_session, organization=secondary_org)
    foreign_document = await _seed_document(
        db_session,
        organization=secondary_org,
        uploader=secondary_user,
        filename="eval-foreign.pdf",
    )
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=primary_org.id,
        name="Auth Guard Set",
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(primary_org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.post(
        "/api/v1/evaluations/run",
        headers=_auth_headers(token=token, organization_id=str(primary_org.id)),
        json={
            "evaluation_set_id": str(evaluation_set.id),
            "config": {
                "selected_document_ids": [str(foreign_document.id)],
            },
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


@pytest.mark.asyncio
async def test_evaluation_admin_only_rejects_member_role(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    evaluation_repository = EvaluationRepository()
    user, org, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    _ = await _seed_document(db_session, organization=org, uploader=user, filename="eval-local.pdf")
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=org.id,
        name="Member Guard Set",
    )
    await db_session.commit()
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await auth_client.post(
        "/api/v1/evaluations/run",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "evaluation_set_id": str(evaluation_set.id),
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Insufficient role for requested operation"


@pytest.mark.asyncio
async def test_auth_login_returns_access_token_and_refresh_cookie(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, _ = await _seed_principal(db_session, role=OrganizationRole.member)

    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["access_token"], str)
    assert payload["refresh_token"] is None
    assert payload["organization_id"] == str(org.id)
    assert payload["role"] == OrganizationRole.member.value

    claims = decode_app_access_token(payload["access_token"])
    assert claims["sub"] == user.external_auth_id
    assert claims["org_id"] == str(org.id)
    _ = _extract_refresh_cookie(response)


@pytest.mark.asyncio
async def test_auth_login_auto_provisions_user_when_email_is_unknown(
    auth_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_auth_auto_provision_users", True)
    email = f"new-{uuid4().hex[:8]}@example.com"

    response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == email
    assert payload["organization_id"] is not None
    assert payload["role"] == OrganizationRole.owner.value

    expected_user = await _repository.get_user_by_email(db_session, email=email)
    assert expected_user is not None
    assert expected_user.memberships


@pytest.mark.asyncio
async def test_refresh_token_rotation_revokes_old_refresh_cookie(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, _, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    login_response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert login_response.status_code == 200
    old_refresh_token = _extract_refresh_cookie(login_response)

    refresh_response = await auth_client.post(
        "/api/v1/auth/token/refresh",
        cookies={"rudix_refresh_token": old_refresh_token},
    )
    assert refresh_response.status_code == 200
    new_refresh_token = _extract_refresh_cookie(refresh_response)
    assert new_refresh_token != old_refresh_token

    replay_response = await auth_client.post(
        "/api/v1/auth/token/refresh",
        cookies={"rudix_refresh_token": old_refresh_token},
    )
    assert replay_response.status_code == 403
    assert replay_response.json()["detail"] == "Refresh token has been revoked"


@pytest.mark.asyncio
async def test_logout_revokes_refresh_cookie(
    auth_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, _, _ = await _seed_principal(db_session, role=OrganizationRole.member)
    login_response = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "password123"},
    )
    assert login_response.status_code == 200
    refresh_token = _extract_refresh_cookie(login_response)

    logout_response = await auth_client.post(
        "/api/v1/auth/logout",
        cookies={"rudix_refresh_token": refresh_token},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {"success": True}

    refresh_response = await auth_client.post(
        "/api/v1/auth/token/refresh",
        cookies={"rudix_refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 403
    assert refresh_response.json()["detail"] == "Refresh token has been revoked"
