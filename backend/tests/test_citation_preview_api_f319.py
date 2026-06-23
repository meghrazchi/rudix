from __future__ import annotations

import os
from datetime import UTC, datetime
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
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.documents.repositories.documents import DocumentRepository
from app.main import app
from app.models.authorization import SourceAclMapping
from app.models.chat import ChatMessage
from app.models.citation import Citation
from app.models.connector import (
    ConnectorConnection,
    ConnectorProvider,
    ExternalItem,
)
from app.models.connector_source import SourceDocument, SourceReference
from app.models.document import Document, DocumentChunk
from app.models.enums import (
    ConnectorAuthType,
    ConnectorConnectionStatus,
    DocumentReviewStatus,
    DocumentStatus,
    ExternalItemType,
    OrganizationRole,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def citation_client(
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


async def _seed_org_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.member,
) -> tuple[Organization, User]:
    org = Organization(name=f"Citation Org {uuid4()}", slug=f"citation-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"citation-user-{uuid4().hex[:8]}",
        email=f"{uuid4().hex[:8]}@example.test",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.flush()
    return org, user


async def _seed_uploaded_citation(
    db_session: AsyncSession,
    *,
    organization: Organization,
    uploader: User,
) -> tuple[Document, DocumentChunk, ChatMessage, Citation]:
    repository = DocumentRepository()
    chat_repository = ChatRepository()

    document = await repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename="uploaded-citation.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"uploads/{uuid4().hex}.pdf",
        status=DocumentStatus.indexed.value,
        source="manual upload",
        language="en",
        checksum="a" * 64,
    )
    await repository.update_document_trust_status(
        db_session,
        document_id=document.id,
        trust_status="current",
        review_status=DocumentReviewStatus.current.value,
    )
    chunk = await repository.create_document_chunk(
        db_session,
        document_id=document.id,
        page_number=2,
        chunk_index=0,
        text="Uploaded evidence passage for citation preview.",
        token_count=14,
        embedding_model=settings.openai_embedding_model,
        index_version=settings.document_index_version,
        qdrant_point_id=f"{document.id}:{uuid4().hex}",
        section_path="Policy > Overview",
        language="en",
        source_start_offset=100,
        source_end_offset=146,
    )
    session = await chat_repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=uploader.id,
        title="Uploaded citation preview",
    )
    message = await chat_repository.create_chat_message(
        db_session,
        chat_session_id=session.id,
        content="assistant answer",
        role="assistant",
    )
    citation = await chat_repository.create_citation(
        db_session,
        chat_message_id=message.id,
        document_id=document.id,
        chunk_id=chunk.id,
        text_snippet="Uploaded evidence passage",
        page_number=2,
        start_offset=0,
        end_offset=25,
        similarity_score=0.91,
        rerank_score=0.94,
    )
    await db_session.commit()
    await db_session.refresh(document)
    await db_session.refresh(chunk)
    await db_session.refresh(message)
    await db_session.refresh(citation)
    return document, chunk, message, citation


async def _seed_connector_citation(
    db_session: AsyncSession,
    *,
    organization: Organization,
    uploader: User,
) -> tuple[Document, DocumentChunk, Citation]:
    repository = DocumentRepository()
    chat_repository = ChatRepository()

    provider = ConnectorProvider(
        key="confluence",
        display_name="Confluence",
        auth_type=ConnectorAuthType.oauth2.value,
        capabilities_json=[],
        config_schema_json={},
        rate_limits_json=[],
        export_formats_json=[],
        is_enabled=True,
    )
    db_session.add(provider)
    await db_session.flush()

    connection = ConnectorConnection(
        organization_id=organization.id,
        provider_id=provider.id,
        display_name="Confluence Workspace",
        status=ConnectorConnectionStatus.active.value,
        auth_config_json={},
        created_by_user_id=uploader.id,
    )
    db_session.add(connection)
    await db_session.flush()

    external_item = ExternalItem(
        organization_id=organization.id,
        connection_id=connection.id,
        provider_item_id="page-123",
        item_type=ExternalItemType.wiki_page.value,
        title="Connector Source Title",
        source_url="https://confluence.example.test/wiki/spaces/ENG/pages/123",
        content_hash="b" * 64,
        source_updated_at=datetime.now(UTC),
        sync_version=5,
        visibility="org_wide",
        metadata_json={},
        permissions_json={"entries": [{"type": "user", "role": "reader"}]},
    )
    db_session.add(external_item)
    await db_session.flush()

    db_session.add(
        SourceAclMapping(
            organization_id=organization.id,
            connector_connection_id=connection.id,
            source_type="connector_source_item",
            source_id=external_item.provider_item_id,
            user_id=uploader.id,
            principal_type="user",
            principal_value=uploader.external_auth_id,
            action="read_only",
            acl_effect="allow",
            is_active=True,
            raw_acl_json={},
            metadata_json={},
        )
    )
    await db_session.flush()

    document = await repository.create_document(
        db_session,
        organization_id=organization.id,
        uploaded_by_user_id=uploader.id,
        filename="connector-source.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"connector/{uuid4().hex}.pdf",
        status=DocumentStatus.indexed.value,
        source="connector import",
        language="en",
        checksum="c" * 64,
    )
    document.connector_external_item_id = external_item.id
    document.ingestion_source = "connector"
    await db_session.flush()

    source_document = SourceDocument(
        organization_id=organization.id,
        external_item_id=external_item.id,
        document_id=document.id,
        content_hash="d" * 64,
        sync_version=5,
        status="active",
        review_status=DocumentReviewStatus.current.value,
    )
    db_session.add(source_document)
    await db_session.flush()

    chunk = await repository.create_document_chunk(
        db_session,
        document_id=document.id,
        page_number=4,
        chunk_index=0,
        text="Connector-backed evidence passage for citation preview.",
        token_count=16,
        embedding_model=settings.openai_embedding_model,
        index_version=settings.document_index_version,
        qdrant_point_id=f"{document.id}:{uuid4().hex}",
        section_path="Section 4.1",
        language="en",
        source_start_offset=300,
        source_end_offset=352,
    )

    source_reference = SourceReference(
        organization_id=organization.id,
        source_document_id=source_document.id,
        external_item_id=external_item.id,
        document_id=document.id,
        chunk_id=chunk.id,
        reference_type="connector_chunk",
        source_url=external_item.source_url,
        title=external_item.title,
        locator_json={
            "provider_key": provider.key,
            "provider_item_id": external_item.provider_item_id,
            "source_section": "Section 4.1",
            "page_number": 4,
        },
        metadata_json={
            "provider_key": provider.key,
            "provider_label": provider.display_name,
            "source_title": external_item.title,
            "source_key": external_item.provider_item_id,
            "source_url": external_item.source_url,
            "source_section": "Section 4.1",
            "content_hash": source_document.content_hash,
            "sync_version": source_document.sync_version,
            "last_synced_at": source_document.updated_at.isoformat(),
            "trust_status": "trusted",
            "acl_snapshot": external_item.permissions_json,
        },
    )
    db_session.add(source_reference)
    await db_session.flush()

    session = await chat_repository.create_chat_session(
        db_session,
        organization_id=organization.id,
        user_id=uploader.id,
        title="Connector citation preview",
    )
    message = await chat_repository.create_chat_message(
        db_session,
        chat_session_id=session.id,
        content="assistant answer",
        role="assistant",
    )
    citation = await chat_repository.create_citation(
        db_session,
        chat_message_id=message.id,
        document_id=document.id,
        chunk_id=chunk.id,
        text_snippet="Connector-backed evidence passage",
        page_number=4,
        start_offset=0,
        end_offset=33,
        similarity_score=0.93,
        rerank_score=0.95,
    )
    await db_session.commit()
    await db_session.refresh(document)
    await db_session.refresh(chunk)
    await db_session.refresh(citation)
    return document, chunk, citation


def _auth_headers(*, token: str, organization_id: str, request_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
        "X-Request-ID": request_id,
    }


@pytest.mark.asyncio
async def test_citation_preview_returns_uploaded_document_data(
    citation_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, user = await _seed_org_user(db_session)
    document, chunk, _message, citation = await _seed_uploaded_citation(
        db_session,
        organization=org,
        uploader=user,
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await citation_client.get(
        f"/api/v1/documents/{document.id}/citations/{citation.id}/preview",
        headers=_auth_headers(
            token=token, organization_id=str(org.id), request_id="req-citation-1"
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["citation_id"] == str(citation.id)
    assert payload["document_id"] == str(document.id)
    assert payload["chunk_id"] == str(chunk.id)
    assert payload["filename"] == "uploaded-citation.pdf"
    assert payload["document_title"] == "uploaded-citation.pdf"
    assert payload["document_type"] == "pdf"
    assert payload["document_owner_email"] == user.email
    assert payload["source_provider"] == "upload"
    assert payload["source_trust_status"] == "uploaded"
    assert payload["source_url"] is None
    assert payload["source_link_allowed"] is False
    assert payload["document_url"].endswith(
        f"/documents/{document.id}?chunk_id={chunk.id}&citation={citation.id}"
    )
    assert payload["snippet"] == "Uploaded evidence passage"
    assert payload["request_id"] == "req-citation-1"


@pytest.mark.asyncio
async def test_citation_preview_returns_connector_source_data(
    citation_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, user = await _seed_org_user(db_session)
    document, _chunk, citation = await _seed_connector_citation(
        db_session,
        organization=org,
        uploader=user,
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await citation_client.get(
        f"/api/v1/documents/{document.id}/citations/{citation.id}/preview",
        headers=_auth_headers(
            token=token, organization_id=str(org.id), request_id="req-citation-2"
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_provider"] == "confluence"
    assert payload["source_provider_label"] == "Confluence"
    assert payload["source_title"] == "Connector Source Title"
    assert payload["source_key"] == "page-123"
    assert payload["source_url"] == "https://confluence.example.test/wiki/spaces/ENG/pages/123"
    assert payload["source_link_allowed"] is True
    assert payload["source_trust_status"] == "trusted"
    assert payload["freshness_state"] == "current"
    assert payload["source_content_hash"] == "d" * 64
    assert payload["source_sync_version"] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutate", "expected_status", "expected_code"),
    [
        (
            {"status": DocumentStatus.processing.value},
            409,
            "citation_not_indexed",
        ),
        (
            {"status": DocumentStatus.deleted.value},
            410,
            "citation_deleted",
        ),
        (
            {"trust_status": "stale", "review_status": DocumentReviewStatus.stale.value},
            409,
            "citation_stale",
        ),
    ],
)
async def test_citation_preview_rejects_inactive_or_stale_sources(
    citation_client: AsyncClient,
    db_session: AsyncSession,
    mutate: dict[str, str],
    expected_status: int,
    expected_code: str,
) -> None:
    org, user = await _seed_org_user(db_session)
    document, _chunk, citation = await _seed_connector_citation(
        db_session,
        organization=org,
        uploader=user,
    )
    repository = DocumentRepository()
    if "status" in mutate:
        await repository.update_document_status(
            db_session,
            document_id=document.id,
            status=mutate["status"],
        )
    if "trust_status" in mutate:
        await repository.update_document_trust_status(
            db_session,
            document_id=document.id,
            trust_status=mutate["trust_status"],
            review_status=mutate["review_status"],
        )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await citation_client.get(
        f"/api/v1/documents/{document.id}/citations/{citation.id}/preview",
        headers=_auth_headers(
            token=token, organization_id=str(org.id), request_id="req-citation-3"
        ),
    )

    assert response.status_code == expected_status
    payload = response.json()
    assert payload["detail"]["code"] == expected_code
    assert payload["detail"]["request_id"] == "req-citation-3"


@pytest.mark.asyncio
async def test_citation_preview_rejects_cross_org_access(
    citation_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    org, user = await _seed_org_user(db_session)
    foreign_org, foreign_user = await _seed_org_user(db_session)
    document, _chunk, _message, citation = await _seed_uploaded_citation(
        db_session,
        organization=org,
        uploader=user,
    )

    token = create_app_access_token(
        subject=foreign_user.external_auth_id,
        organization_id=str(foreign_org.id),
        expires_in_seconds=600,
    )
    response = await citation_client.get(
        f"/api/v1/documents/{document.id}/citations/{citation.id}/preview",
        headers=_auth_headers(
            token=token, organization_id=str(foreign_org.id), request_id="req-citation-4"
        ),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("citation_id", ["not-a-uuid", str(uuid4())])
async def test_citation_preview_returns_not_found_for_missing_citations(
    citation_client: AsyncClient,
    db_session: AsyncSession,
    citation_id: str,
) -> None:
    org, user = await _seed_org_user(db_session)
    document, _chunk, _message, _citation = await _seed_uploaded_citation(
        db_session,
        organization=org,
        uploader=user,
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await citation_client.get(
        f"/api/v1/documents/{document.id}/citations/{citation_id}/preview",
        headers=_auth_headers(
            token=token, organization_id=str(org.id), request_id="req-citation-5"
        ),
    )

    assert response.status_code == 404
    if citation_id == "not-a-uuid":
        assert response.json()["detail"]["code"] == "citation_not_found"
