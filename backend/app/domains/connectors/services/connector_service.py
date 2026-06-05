from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.services.audit_service import sanitize_metadata
from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.schemas.connectors import (
    NormalizedExternalItem,
    ProviderRegistration,
)
from app.domains.connectors.services.provider_registry import (
    ProviderRegistry,
    default_provider_registry,
)
from app.models.collection import Collection
from app.models.connector import (
    ConnectorConnection,
    ConnectorProvider,
    ExternalItem,
    ExternalSource,
)
from app.models.connector_source import SourceDocument
from app.models.document import Document


class ConnectorBoundaryError(ValueError):
    """Raised when a connector operation crosses an org or collection boundary."""


class ConnectorPlatformService:
    def __init__(
        self,
        *,
        repository: ConnectorRepository | None = None,
        provider_registry: ProviderRegistry | None = None,
    ) -> None:
        self.repository = repository or ConnectorRepository()
        self.provider_registry = provider_registry or default_provider_registry

    async def register_provider(
        self,
        session: AsyncSession,
        *,
        registration: ProviderRegistration,
    ) -> ConnectorProvider:
        if self.provider_registry.get(registration.key) is None:
            self.provider_registry.register(registration)
        return await self.repository.upsert_provider(session, registration=registration)

    async def create_connection(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        provider_key: str,
        display_name: str,
        collection_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        external_account_id: str | None = None,
        auth_config: dict | None = None,
    ) -> ConnectorConnection:
        registration = self.provider_registry.require(provider_key)
        if collection_id is not None:
            await self.require_collection(session, organization_id, collection_id)
        provider = await self.repository.upsert_provider(session, registration=registration)
        connection = await self.repository.create_connection(
            session,
            organization_id=organization_id,
            provider_id=provider.id,
            collection_id=collection_id,
            created_by_user_id=created_by_user_id,
            external_account_id=external_account_id,
            display_name=display_name,
            auth_config=sanitize_metadata(auth_config),
        )
        connection.provider = provider
        return connection

    async def create_external_source(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        provider_source_id: str,
        source_type: str,
        name: str,
        collection_id: UUID | None = None,
        source_url: str | None = None,
        config: dict | None = None,
        permissions: dict | None = None,
    ) -> ExternalSource:
        connection = await self.require_connection(session, organization_id, connection_id)
        effective_collection_id = collection_id or connection.collection_id
        if effective_collection_id is not None:
            await self.require_collection(session, organization_id, effective_collection_id)
        return await self.repository.create_external_source(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            collection_id=effective_collection_id,
            provider_source_id=provider_source_id,
            source_type=source_type,
            name=name,
            source_url=source_url,
            config=config,
            permissions=permissions,
        )

    async def upsert_external_item(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        item: NormalizedExternalItem,
    ) -> ExternalItem:
        if item.organization_id != organization_id:
            raise ConnectorBoundaryError("external item organization does not match caller")
        self.provider_registry.require(item.provider_key)
        if item.connection_id is None:
            raise ConnectorBoundaryError("external item requires a connector connection")
        connection = await self.require_connection(session, organization_id, item.connection_id)
        if item.external_source_id is not None:
            source = await self.require_external_source(
                session, organization_id, item.external_source_id
            )
            if source.connection_id != connection.id:
                raise ConnectorBoundaryError(
                    "external source does not belong to connector connection"
                )
        effective_collection_id = item.collection_id or connection.collection_id
        if effective_collection_id is not None:
            await self.require_collection(session, organization_id, effective_collection_id)
        normalized_item = item.model_copy(update={"collection_id": effective_collection_id})
        return await self.repository.upsert_external_item(session, item=normalized_item)

    async def link_source_document(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        external_item_id: UUID,
        document_id: UUID,
        content_hash: str,
        sync_version: int,
        collection_id: UUID | None = None,
    ) -> SourceDocument:
        item = await self.repository.get_external_item(
            session,
            organization_id=organization_id,
            external_item_id=external_item_id,
        )
        if item is None:
            raise ConnectorBoundaryError("external item not found for organization")
        document = await self.require_document(session, organization_id, document_id)
        effective_collection_id = collection_id or item.collection_id
        if effective_collection_id is not None:
            await self.require_collection(session, organization_id, effective_collection_id)
        return await self.repository.link_source_document(
            session,
            organization_id=organization_id,
            external_item_id=item.id,
            document_id=document.id,
            collection_id=effective_collection_id,
            content_hash=content_hash,
            sync_version=sync_version,
        )

    async def require_connection(
        self,
        session: AsyncSession,
        organization_id: UUID,
        connection_id: UUID,
    ) -> ConnectorConnection:
        connection = await self.repository.get_connection(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        if connection is None:
            raise ConnectorBoundaryError("connector connection not found for organization")
        return connection

    async def require_external_source(
        self,
        session: AsyncSession,
        organization_id: UUID,
        external_source_id: UUID,
    ) -> ExternalSource:
        source = await self.repository.get_external_source(
            session,
            organization_id=organization_id,
            external_source_id=external_source_id,
        )
        if source is None:
            raise ConnectorBoundaryError("external source not found for organization")
        return source

    async def require_collection(
        self,
        session: AsyncSession,
        organization_id: UUID,
        collection_id: UUID,
    ) -> Collection:
        result = await session.execute(
            select(Collection).where(
                Collection.id == collection_id,
                Collection.organization_id == organization_id,
                Collection.is_archived.is_(False),
            )
        )
        collection = result.scalar_one_or_none()
        if collection is None:
            raise ConnectorBoundaryError("collection not found for organization")
        return collection

    async def require_document(
        self,
        session: AsyncSession,
        organization_id: UUID,
        document_id: UUID,
    ) -> Document:
        result = await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise ConnectorBoundaryError("document not found for organization")
        return document
