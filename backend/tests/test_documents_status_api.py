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
from app.core.document_errors import build_document_error_details, encode_document_error
from app.db.session import get_db_session
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.repositories.documents import DocumentRepository


@pytest_asyncio.fixture
async def status_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_document(
    db_session: AsyncSession,
    *,
    status: DocumentStatus,
    error_message: str | None = None,
) -> tuple[User, Organization, Document]:
    organization = Organization(name="Status Org", slug=f"status-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"status-user-{uuid4().hex[:8]}",
        email=f"status-{uuid4().hex[:8]}@example.com",
        display_name="Status User",
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
    await db_session.flush()

    document_repository = DocumentRepository()
    document = await document_repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=user.id,
        filename="status.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"uploads/{organization.id}/{user.id}/{uuid4()}.pdf",
        status=status.value,
    )
    document.error_message = error_message
    await db_session.commit()
    await db_session.refresh(document)
    return user, organization, document


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
async def test_get_document_status_returns_uploaded_state(
    status_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization, document = await _seed_document(
        db_session,
        status=DocumentStatus.uploaded,
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await status_client.get(
        f"/api/v1/documents/{document.id}",
        headers=_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == str(document.id)
    assert payload["status"] == DocumentStatus.uploaded.value
    assert payload["error_message"] is None
    assert payload["error_details"] is None


@pytest.mark.asyncio
async def test_get_document_status_decodes_structured_error_details(
    status_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    encoded_error = encode_document_error(
        build_document_error_details(
            stage="embed",
            code="EMBEDDING_FAILED_TRANSIENT",
            category="infrastructure",
            retryable=True,
            message="embedding provider timeout",
        )
    )
    user, organization, document = await _seed_document(
        db_session,
        status=DocumentStatus.failed,
        error_message=encoded_error,
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await status_client.get(
        f"/api/v1/documents/{document.id}",
        headers=_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == DocumentStatus.failed.value
    assert payload["error_message"] == "embedding provider timeout"
    assert payload["error_details"] == {
        "stage": "embed",
        "code": "EMBEDDING_FAILED_TRANSIENT",
        "category": "infrastructure",
        "retryable": True,
        "message": "embedding provider timeout",
    }
