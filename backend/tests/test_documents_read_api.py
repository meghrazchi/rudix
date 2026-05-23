import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure strict settings can be loaded when importing modules in tests.
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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.clients import minio_client as minio_module
from app.core.config import AuthProvider, settings
from app.core.document_errors import build_document_error_details, encode_document_error
from app.db.session import get_db_session
from app.domains.documents.repositories.documents import DocumentRepository
from app.main import app
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


class FakeObjectBody:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False

    def read(self) -> bytes:
        return self.content

    def close(self) -> None:
        self.closed = True


class FakeMinioForDownload:
    def __init__(self, *, content: bytes) -> None:
        self.content = content
        self.calls: list[dict[str, object]] = []
        self.raise_error = False
        self.last_body: FakeObjectBody | None = None

    def get_object(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.raise_error:
            raise RuntimeError("storage unavailable")
        body = FakeObjectBody(self.content)
        self.last_body = body
        return {"Body": body}


@pytest_asyncio.fixture
async def documents_client(
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


async def _seed_principal(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.member,
) -> tuple[User, Organization, Organization]:
    primary_org = Organization(name="Read Primary", slug=f"read-primary-{uuid4().hex[:8]}")
    secondary_org = Organization(name="Read Secondary", slug=f"read-secondary-{uuid4().hex[:8]}")
    db_session.add_all([primary_org, secondary_org])
    await db_session.flush()

    user = User(
        organization_id=primary_org.id,
        external_auth_id=f"read-user-{uuid4().hex[:8]}",
        email=f"read-{uuid4().hex[:8]}@example.com",
        display_name="Read API User",
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
        external_auth_id=f"read-org-user-{uuid4().hex[:8]}",
        email=f"read-org-{uuid4().hex[:8]}@example.com",
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
    status: DocumentStatus,
    page_count: int | None = None,
    error_message: str | None = None,
) -> Document:
    repository = DocumentRepository()
    document = await repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename=filename,
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"seed/{filename}-{uuid4()}.pdf",
        status=status.value,
    )
    if page_count is not None or error_message is not None:
        _ = await repository.update_document_status(
            db_session,
            document_id=document.id,
            status=status.value,
            page_count=page_count,
            error_message=error_message,
        )
    await db_session.commit()
    await db_session.refresh(document)
    return document


async def _seed_chunks(
    db_session: AsyncSession,
    *,
    document_id: UUID,
    count: int,
) -> None:
    repository = DocumentRepository()
    for idx in range(count):
        await repository.create_document_chunk(
            db_session,
            document_id=document_id,
            page_number=(idx // 2) + 1,
            chunk_index=idx,
            text=f"chunk-{idx} content " + ("x" * 260),
            token_count=50 + idx,
            embedding_model=settings.openai_embedding_model,
            index_version=settings.document_index_version,
            qdrant_point_id=f"{document_id}:{settings.document_index_version}:{idx}",
        )
    await db_session.commit()


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
async def test_documents_list_filters_by_org_and_status_with_pagination(
    documents_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, other_org = await _seed_principal(db_session)
    other_user = await _seed_user_for_org(db_session, organization=other_org)

    doc_indexed = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        filename="indexed.pdf",
        status=DocumentStatus.indexed,
        page_count=3,
    )
    await _seed_chunks(db_session, document_id=doc_indexed.id, count=3)
    _ = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        filename="processing.pdf",
        status=DocumentStatus.processing,
        page_count=1,
    )
    _ = await _seed_document(
        db_session,
        organization=other_org,
        uploader=other_user,
        filename="foreign.pdf",
        status=DocumentStatus.indexed,
        page_count=8,
    )

    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    response = await documents_client.get(
        "/api/v1/documents",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        params={
            "status": "indexed",
            "limit": 1,
            "offset": 0,
            "sort_by": "filename",
            "sort_order": "asc",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["status"] == "indexed"
    assert payload["sort_by"] == "filename"
    assert payload["sort_order"] == "asc"
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["document_id"] == str(doc_indexed.id)
    assert item["filename"] == "indexed.pdf"
    assert item["chunk_count"] == 3
    assert item["page_count"] == 3


@pytest.mark.asyncio
async def test_document_detail_returns_metadata_and_safe_error_summary(
    documents_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, _ = await _seed_principal(db_session)

    plain_error_doc = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        filename="legacy-failure.pdf",
        status=DocumentStatus.failed,
        error_message="backend traceback details",
    )
    structured_error_doc = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        filename="structured-failure.pdf",
        status=DocumentStatus.failed,
        error_message=encode_document_error(
            build_document_error_details(
                stage="index",
                code="QDRANT_UPSERT_FAILED",
                category="infrastructure",
                retryable=True,
                message="qdrant upsert failed",
            )
        ),
    )

    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    plain_response = await documents_client.get(
        f"/api/v1/documents/{plain_error_doc.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert plain_response.status_code == 200
    plain_payload = plain_response.json()
    assert plain_payload["document_id"] == str(plain_error_doc.id)
    assert plain_payload["status"] == "failed"
    assert plain_payload["error_message"] == "Processing failed"
    assert plain_payload["error_details"] is None

    structured_response = await documents_client.get(
        f"/api/v1/documents/{structured_error_doc.id}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert structured_response.status_code == 200
    structured_payload = structured_response.json()
    assert structured_payload["error_message"] == "qdrant upsert failed"
    assert structured_payload["error_details"]["code"] == "QDRANT_UPSERT_FAILED"


@pytest.mark.asyncio
async def test_document_chunks_endpoint_paginates_and_hides_full_text_by_default(
    documents_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, _ = await _seed_principal(db_session)
    document = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        filename="chunked.pdf",
        status=DocumentStatus.indexed,
        page_count=5,
    )
    await _seed_chunks(db_session, document_id=document.id, count=5)

    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await documents_client.get(
        f"/api/v1/documents/{document.id}/chunks",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        params={"limit": 2, "offset": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == str(document.id)
    assert payload["total"] == 5
    assert payload["limit"] == 2
    assert payload["offset"] == 1
    assert payload["include_full_text"] is False
    assert len(payload["items"]) == 2


@pytest.mark.asyncio
async def test_document_download_streams_file_for_authorized_user(
    documents_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org, _ = await _seed_principal(db_session)
    document = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        filename="download-policy.pdf",
        status=DocumentStatus.indexed,
        page_count=3,
    )
    fake_minio = FakeMinioForDownload(content=b"%PDF-1.7\nmock")
    monkeypatch.setattr(minio_module, "minio_client", fake_minio)

    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    response = await documents_client.get(
        f"/api/v1/documents/{document.id}/download",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7\nmock"
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment;" in response.headers["content-disposition"]
    assert "download-policy.pdf" in response.headers["content-disposition"]
    assert len(fake_minio.calls) == 1
    assert fake_minio.calls[0]["Bucket"] == document.storage_bucket
    assert fake_minio.calls[0]["Key"] == document.storage_object_key
    assert fake_minio.last_body is not None and fake_minio.last_body.closed is True


@pytest.mark.asyncio
async def test_document_download_returns_503_when_storage_unavailable(
    documents_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, org, _ = await _seed_principal(db_session)
    document = await _seed_document(
        db_session,
        organization=org,
        uploader=user,
        filename="unavailable.pdf",
        status=DocumentStatus.indexed,
    )
    fake_minio = FakeMinioForDownload(content=b"")
    fake_minio.raise_error = True
    monkeypatch.setattr(minio_module, "minio_client", fake_minio)

    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    response = await documents_client.get(
        f"/api/v1/documents/{document.id}/download",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Document file is unavailable"


@pytest.mark.asyncio
async def test_document_chunks_rejects_cross_organization_access(
    documents_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org, other_org = await _seed_principal(db_session)
    other_user = await _seed_user_for_org(db_session, organization=other_org)
    foreign_document = await _seed_document(
        db_session,
        organization=other_org,
        uploader=other_user,
        filename="foreign-chunks.pdf",
        status=DocumentStatus.indexed,
    )

    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    response = await documents_client.get(
        f"/api/v1/documents/{foreign_document.id}/chunks",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"
