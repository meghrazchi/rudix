"""Read-side lookups used by document routes (kept out of the HTTP layer, R04-13)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authorization import SourceAclMapping
from app.models.collection import Collection, CollectionDocument
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_source import SourceDocument
from app.models.document import Document
from app.models.organization import Organization


class DocumentLookupRepository:
    async def has_user_source_acl_allow(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        connection_id: UUID,
    ) -> bool:
        result = await session.execute(
            select(SourceAclMapping.id).where(
                SourceAclMapping.organization_id == organization_id,
                SourceAclMapping.connector_connection_id == connection_id,
                SourceAclMapping.user_id == user_id,
                SourceAclMapping.principal_type == "user",
                SourceAclMapping.acl_effect == "allow",
                SourceAclMapping.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none() is not None

    async def collections_for_documents(
        self, session: AsyncSession, *, document_ids: Sequence[Any]
    ) -> list[tuple[Any, Any, str]]:
        """(document_id, collection_id, collection_name) for non-archived collections."""
        result = await session.execute(
            select(CollectionDocument.document_id, Collection.id, Collection.name)
            .join(Collection, CollectionDocument.collection_id == Collection.id)
            .where(
                CollectionDocument.document_id.in_(document_ids),
                Collection.is_archived.is_(False),
            )
            .order_by(Collection.name)
        )
        return [(row[0], row[1], row[2]) for row in result]

    async def source_providers_for_documents(
        self, session: AsyncSession, *, document_ids: Sequence[Any]
    ) -> dict[Any, str]:
        """Connector provider key per document. DISTINCT ON is Postgres-only (as before)."""
        result = await session.execute(
            select(SourceDocument.document_id, ConnectorProvider.key)
            .join(ExternalItem, ExternalItem.id == SourceDocument.external_item_id)
            .join(ConnectorConnection, ConnectorConnection.id == ExternalItem.connection_id)
            .join(ConnectorProvider, ConnectorProvider.id == ConnectorConnection.provider_id)
            .where(SourceDocument.document_id.in_(document_ids))
            .distinct(SourceDocument.document_id)
        )
        return {doc_id: provider_key for doc_id, provider_key in result}

    async def sample_docs_enabled(self, session: AsyncSession, *, organization_id: UUID) -> bool:
        result = await session.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        org = result.scalar_one_or_none()
        return bool(org is not None and org.sample_docs_enabled)

    async def sample_document_filenames(
        self, session: AsyncSession, *, organization_id: UUID
    ) -> set[str]:
        result = await session.execute(
            select(Document.filename).where(
                Document.organization_id == organization_id,
                Document.source == "sample-dataset",
            )
        )
        return {row[0] for row in result.all()}
