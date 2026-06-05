from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access
from app.auth.models import AuthenticatedPrincipal
from app.domains.connectors.services.source_provenance import SourceProvenanceService
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_source import SourceDocument, SourceReference
from app.models.document import Document, DocumentChunk
from app.models.enums import ConnectorAuthType, ConnectorConnectionStatus, ExternalItemType
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


async def _create_connector_document(
    db_session: AsyncSession,
    *,
    provider_key: str = "jira",
    connection_status: str = ConnectorConnectionStatus.active.value,
    deleted_at: datetime | None = None,
) -> tuple[Organization, User, Document, DocumentChunk, ExternalItem]:
    org = Organization(
        name=f"Org {uuid4()}",
        slug=f"org-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"user-{uuid4()}",
        email=f"{uuid4().hex[:8]}@example.test",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="admin"))
    await db_session.flush()

    provider_result = await db_session.execute(
        select(ConnectorProvider).where(ConnectorProvider.key == provider_key)
    )
    provider = provider_result.scalar_one_or_none()
    if provider is None:
        provider = ConnectorProvider(
            key=provider_key,
            display_name=provider_key.title(),
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
        organization_id=org.id,
        provider_id=provider.id,
        display_name=f"{provider_key.title()} Connection",
        status=connection_status,
        auth_config_json={},
        created_by_user_id=user.id,
    )
    db_session.add(connection)
    await db_session.flush()

    external_item = ExternalItem(
        organization_id=org.id,
        connection_id=connection.id,
        provider_item_id=f"{provider_key}-123",
        item_type=ExternalItemType.cloud_file.value,
        title="Source Title",
        source_url=f"https://{provider_key}.example.test/items/{provider_key}-123",
        content_hash="a" * 64,
        source_updated_at=datetime.now(UTC),
        sync_version=3,
        visibility="org_wide",
        metadata_json={},
        permissions_json={"entries": [{"type": "user", "role": "reader"}]},
        deleted_at=deleted_at,
    )
    db_session.add(external_item)
    await db_session.flush()

    document = Document(
        organization_id=org.id,
        uploaded_by_user_id=user.id,
        filename="source.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key="documents/source.pdf",
        status="indexed",
        connector_external_item_id=external_item.id,
        ingestion_source="connector",
    )
    db_session.add(document)
    await db_session.flush()

    source_document = SourceDocument(
        organization_id=org.id,
        external_item_id=external_item.id,
        document_id=document.id,
        content_hash="b" * 64,
        sync_version=3,
        status="active",
    )
    db_session.add(source_document)
    await db_session.flush()

    chunk = DocumentChunk(
        document_id=document.id,
        page_number=1,
        chunk_index=0,
        text="Connector backed chunk text.",
        token_count=10,
        embedding_model="test-embedding",
        index_version="v1",
        qdrant_point_id=str(uuid4()),
        chunk_hash="c" * 64,
        section_path="Page 1",
        language="en",
    )
    db_session.add(chunk)
    await db_session.flush()

    source_reference = SourceReference(
        organization_id=org.id,
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
            "source_section": "Page 1",
            "page_number": 1,
        },
        metadata_json={
            "provider_key": provider.key,
            "provider_label": provider.display_name,
            "source_title": external_item.title,
            "source_key": external_item.provider_item_id,
            "source_url": external_item.source_url,
            "source_section": "Page 1",
            "content_hash": source_document.content_hash,
            "sync_version": source_document.sync_version,
            "last_synced_at": source_document.updated_at.isoformat(),
            "trust_status": "trusted" if deleted_at is None else "deleted",
            "acl_snapshot": external_item.permissions_json,
        },
    )
    db_session.add(source_reference)
    await db_session.flush()

    doc_reference = SourceReference(
        organization_id=org.id,
        source_document_id=source_document.id,
        external_item_id=external_item.id,
        document_id=document.id,
        chunk_id=None,
        reference_type="connector_file",
        source_url=external_item.source_url,
        title=external_item.title,
        locator_json={
            "provider_key": provider.key,
            "provider_item_id": external_item.provider_item_id,
        },
        metadata_json={
            "provider_key": provider.key,
            "provider_label": provider.display_name,
            "source_title": external_item.title,
            "source_key": external_item.provider_item_id,
            "source_url": external_item.source_url,
            "content_hash": source_document.content_hash,
            "sync_version": source_document.sync_version,
            "last_synced_at": source_document.updated_at.isoformat(),
            "trust_status": "trusted" if deleted_at is None else "deleted",
            "acl_snapshot": external_item.permissions_json,
        },
    )
    db_session.add(doc_reference)
    await db_session.flush()

    return org, user, document, chunk, external_item


@pytest.mark.asyncio
async def test_source_provenance_loads_connector_citation_details(
    db_session: AsyncSession,
) -> None:
    org, _, document, chunk, _ = await _create_connector_document(db_session)
    service = SourceProvenanceService()

    details_by_chunk = await service.load_citation_details(
        db_session,
        organization_id=org.id,
        chunk_ids=[chunk.id],
    )

    details = details_by_chunk[chunk.id]
    assert details.provider_key == "jira"
    assert details.provider_label == "Jira"
    assert details.source_title == "Source Title"
    assert details.source_section == "Page 1"
    assert details.source_deep_link == "https://jira.example.test/items/jira-123"
    assert details.source_trust_status == "trusted"
    assert details.source_sync_version == 3
    assert details.source_acl_snapshot["entries"][0]["role"] == "reader"

    document_details = await service.load_citation_details_for_documents(
        db_session,
        organization_id=org.id,
        document_ids=[document.id],
    )
    assert document_details[document.id].source_title == "Source Title"


@pytest.mark.asyncio
async def test_source_provenance_filters_deleted_connector_sources(
    db_session: AsyncSession,
) -> None:
    org, user, document, chunk, _external_item = await _create_connector_document(
        db_session,
        deleted_at=datetime.now(UTC),
    )
    service = SourceProvenanceService()

    filtered_chunks = await service.filter_active_chunks(
        db_session,
        organization_id=org.id,
        chunks=[
            type(
                "Chunk",
                (),
                {"document_id": document.id, "chunk_id": chunk.id},
            )(),
        ],
    )

    assert filtered_chunks == []

    details_by_chunk = await service.load_citation_details(
        db_session,
        organization_id=org.id,
        chunk_ids=[chunk.id],
    )
    assert details_by_chunk[chunk.id].source_trust_status == "deleted"

    principal = AuthenticatedPrincipal(
        user_id=str(user.id),
        organization_id=str(org.id),
        roles=["member"],
        auth_provider="app",
    )
    with pytest.raises(HTTPException) as exc_info:
        await ensure_document_ids_access(
            document_ids=[str(document.id)],
            principal=principal,
            db_session=db_session,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_source_provenance_marks_out_of_sync_sources_as_stale(
    db_session: AsyncSession,
) -> None:
    org, _, _, chunk, external_item = await _create_connector_document(db_session)
    external_item.content_hash = "d" * 64
    external_item.sync_version = 4
    await db_session.flush()

    service = SourceProvenanceService()
    details_by_chunk = await service.load_citation_details(
        db_session,
        organization_id=org.id,
        chunk_ids=[chunk.id],
    )

    details = details_by_chunk[chunk.id]
    assert details.source_trust_status == "stale"
    assert details.source_key == external_item.provider_item_id


@pytest.mark.asyncio
async def test_source_provenance_blocks_cross_tenant_chunk_lookup(
    db_session: AsyncSession,
) -> None:
    org_one, _, _, chunk_one, _ = await _create_connector_document(db_session)
    _org_two, _, _, chunk_two, _ = await _create_connector_document(db_session)
    service = SourceProvenanceService()

    details_by_chunk = await service.load_citation_details(
        db_session,
        organization_id=org_one.id,
        chunk_ids=[chunk_one.id, chunk_two.id],
    )

    assert chunk_one.id in details_by_chunk
    assert chunk_two.id not in details_by_chunk
