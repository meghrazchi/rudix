"""Tests for admin document language override endpoint (F230)."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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

from app.auth.token_codec import create_app_access_token
from app.db.session import get_db_session
from app.domains.documents.repositories.documents import DocumentRepository
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

document_repository = DocumentRepository()


def _make_token(user_id: str, org_id: str, role: str) -> str:
    return create_app_access_token(
        user_id=user_id,
        organization_id=org_id,
        roles=[role],
        secret="test-secret",
        issuer="rudix-app",
        audience="rudix-api",
        ttl_seconds=3600,
    )


@pytest_asyncio.fixture
async def admin_client(db_session: AsyncSession):
    org_id = uuid4()
    user_id = uuid4()

    org = Organization(id=org_id, name="Test Org", slug=f"test-{org_id}")
    user = User(id=user_id, email=f"admin-{user_id}@example.com", hashed_password="x")
    member = OrganizationMember(
        organization_id=org_id, user_id=user_id, role=OrganizationRole.admin.value
    )
    db_session.add_all([org, user, member])
    await db_session.flush()

    token = _make_token(str(user_id), str(org_id), OrganizationRole.admin.value)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, org_id, user_id


@pytest_asyncio.fixture
async def member_client(db_session: AsyncSession):
    org_id = uuid4()
    user_id = uuid4()

    org = Organization(id=org_id, name="Member Org", slug=f"member-{org_id}")
    user = User(id=user_id, email=f"member-{user_id}@example.com", hashed_password="x")
    member = OrganizationMember(
        organization_id=org_id, user_id=user_id, role=OrganizationRole.member.value
    )
    db_session.add_all([org, user, member])
    await db_session.flush()

    token = _make_token(str(user_id), str(org_id), OrganizationRole.member.value)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client, org_id, user_id


async def _create_doc(
    db_session: AsyncSession,
    *,
    org_id: UUID,
    user_id: UUID,
    language: str | None = None,
    language_source: str | None = None,
) -> Document:
    doc = await document_repository.create_document(
        db_session,
        organization_id=org_id,
        uploaded_by_user_id=user_id,
        filename="test.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"test/{uuid4()}.pdf",
        status=DocumentStatus.indexed.value,
        language=language,
        language_source=language_source,
    )
    await db_session.flush()
    return doc


@pytest.mark.asyncio
async def test_admin_can_override_language(admin_client, db_session: AsyncSession) -> None:
    client, org_id, user_id = admin_client

    app.dependency_overrides[get_db_session] = lambda: db_session

    doc = await _create_doc(
        db_session, org_id=org_id, user_id=user_id, language="en", language_source="auto_detected"
    )

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/language",
        json={"language": "de"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["language"] == "de"
    assert data["language_source"] == "admin_override"
    assert data["language_confidence"] is None


@pytest.mark.asyncio
async def test_admin_can_clear_language_override(admin_client, db_session: AsyncSession) -> None:
    client, org_id, user_id = admin_client

    app.dependency_overrides[get_db_session] = lambda: db_session

    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id, language="es")

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/language",
        json={"language": None},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["language"] is None
    assert data["language_source"] == "admin_override"


@pytest.mark.asyncio
async def test_admin_override_rejects_unsupported_language(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client

    app.dependency_overrides[get_db_session] = lambda: db_session

    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/language",
        json={"language": "klingon"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_member_cannot_override_language(member_client, db_session: AsyncSession) -> None:
    client, org_id, user_id = member_client

    app.dependency_overrides[get_db_session] = lambda: db_session

    doc = await _create_doc(db_session, org_id=org_id, user_id=user_id)

    response = await client.patch(
        f"/api/v1/admin/documents/{doc.id}/language",
        json={"language": "de"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_override_for_other_org_document_returns_404(
    admin_client, db_session: AsyncSession
) -> None:
    client, _org_id, _user_id = admin_client

    app.dependency_overrides[get_db_session] = lambda: db_session

    # Create document under a different org
    other_org = Organization(id=uuid4(), name="Other Org", slug=f"other-{uuid4()}")
    other_user = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="x")
    db_session.add_all([other_org, other_user])
    await db_session.flush()

    other_doc = await _create_doc(db_session, org_id=other_org.id, user_id=other_user.id)

    response = await client.patch(
        f"/api/v1/admin/documents/{other_doc.id}/language",
        json={"language": "de"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_document_detail_exposes_language_fields(
    admin_client, db_session: AsyncSession
) -> None:
    client, org_id, user_id = admin_client

    app.dependency_overrides[get_db_session] = lambda: db_session

    doc = await _create_doc(
        db_session,
        org_id=org_id,
        user_id=user_id,
        language="fr",
        language_source="auto_detected",
    )
    doc.language_confidence = 0.82
    await db_session.flush()

    response = await client.get(f"/api/v1/documents/{doc.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["language"] == "fr"
    assert data["language_source"] == "auto_detected"
    assert abs(data["language_confidence"] - 0.82) < 0.01


@pytest.mark.asyncio
async def test_document_list_language_filter(admin_client, db_session: AsyncSession) -> None:
    client, org_id, user_id = admin_client

    app.dependency_overrides[get_db_session] = lambda: db_session

    await _create_doc(db_session, org_id=org_id, user_id=user_id, language="de")
    await _create_doc(db_session, org_id=org_id, user_id=user_id, language="en")
    await db_session.flush()

    response = await client.get("/api/v1/documents", params={"language": "de"})

    assert response.status_code == 200
    data = response.json()
    assert all(item["language"] == "de" for item in data["items"])
