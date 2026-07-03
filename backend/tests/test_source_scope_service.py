from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.schemas.chat import SourceScopeRequest
from app.domains.chat.services.source_scope_service import SourceScopeService
from app.models.connector import (
    ConnectorConnection,
    ConnectorProvider,
    ExternalItem,
)
from app.models.connector_source import SourceDocument
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest.mark.asyncio
async def test_resolve_document_ids_includes_connector_documents_without_direct_item_link(
    db_session: AsyncSession,
) -> None:
    organization = Organization(name="Connector Scope Org", slug=f"connector-scope-{uuid4().hex}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"user-{uuid4().hex}",
        email=f"{uuid4().hex}@example.com",
        display_name="Connector Scope User",
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

    provider = ConnectorProvider(
        key="confluence",
        display_name="Confluence",
        auth_type="oauth2",
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
        display_name="Confluence Connection",
        status="active",
        auth_config_json={},
        created_by_user_id=user.id,
    )
    db_session.add(connection)
    await db_session.flush()

    external_item = ExternalItem(
        organization_id=organization.id,
        connection_id=connection.id,
        external_source_id=None,
        collection_id=None,
        provider_item_id="page-1",
        item_type="wiki_page",
        title="Connector-backed page",
        source_url="https://example.test/wiki/page-1",
        content_hash="a" * 64,
        source_updated_at=datetime.now(UTC),
        sync_version=1,
        visibility="org_wide",
        metadata_json={},
        permissions_json={},
        deleted_at=None,
    )
    db_session.add(external_item)
    await db_session.flush()

    document = Document(
        organization_id=organization.id,
        uploaded_by_user_id=user.id,
        filename="connector-backed.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"documents/{uuid4()}.pdf",
        status=DocumentStatus.indexed.value,
        checksum="b" * 64,
        ingestion_source="connector",
    )
    document.connector_external_item_id = None
    db_session.add(document)
    await db_session.flush()
    db_session.add(
        SourceDocument(
            organization_id=organization.id,
            external_item_id=external_item.id,
            document_id=document.id,
            content_hash="c" * 64,
            sync_version=1,
            status="active",
        )
    )
    await db_session.flush()

    service = SourceScopeService()
    resolved = await service.resolve_document_ids(
        db_session,
        organization_id=organization.id,
        user_id=user.id,
        user_roles=[OrganizationRole.member.value],
        explicit_document_ids=None,
        source_scope=SourceScopeRequest(
            mode="connector_sources",
            connection_ids=[str(connection.id)],
        ),
    )

    assert resolved.document_ids == [document.id]
