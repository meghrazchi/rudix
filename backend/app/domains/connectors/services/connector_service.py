from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.services.audit_service import AuditLogService, sanitize_metadata
from app.domains.connectors.audit import ConnectorAuditAction
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
        audit_service: AuditLogService | None = None,
    ) -> None:
        self.repository = repository or ConnectorRepository()
        self.provider_registry = provider_registry or default_provider_registry
        self.audit_service = audit_service or AuditLogService()

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
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=created_by_user_id,
            action=ConnectorAuditAction.connection_created.value,
            resource_type="connector_connection",
            resource_id=connection.id,
            metadata={
                "provider_key": provider.key,
                "display_name": display_name,
                "collection_id": str(collection_id) if collection_id else None,
                "external_account_id": external_account_id,
            },
        )
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
        source = await self.repository.create_external_source(
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
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=None,
            action=ConnectorAuditAction.source_selected.value,
            resource_type="external_source",
            resource_id=source.id,
            metadata={
                "connection_id": str(connection_id),
                "provider_source_id": provider_source_id,
                "source_type": source_type,
                "name": name,
                "collection_id": str(effective_collection_id) if effective_collection_id else None,
            },
        )
        return source

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
        existing_result = await session.execute(
            select(ExternalItem).where(
                ExternalItem.organization_id == organization_id,
                ExternalItem.connection_id == item.connection_id,
                ExternalItem.provider_item_id == item.provider_item_id,
            )
        )
        existing = existing_result.scalar_one_or_none()
        previous_state = None
        if existing is not None:
            previous_state = {
                "external_source_id": existing.external_source_id,
                "collection_id": existing.collection_id,
                "visibility": existing.visibility,
                "acl_hash": existing.acl_hash,
                "permissions_json": dict(existing.permissions_json or {}),
                "deleted_at": existing.deleted_at,
            }
        normalized_item = item.model_copy(update={"collection_id": effective_collection_id})
        external_item = await self.repository.upsert_external_item(session, item=normalized_item)
        if previous_state is not None:
            changed_fields: list[str] = []
            if previous_state["external_source_id"] != external_item.external_source_id:
                changed_fields.append("external_source_id")
            if previous_state["collection_id"] != external_item.collection_id:
                changed_fields.append("collection_id")
            if previous_state["visibility"] != external_item.visibility:
                changed_fields.append("visibility")
            if previous_state["acl_hash"] != external_item.acl_hash:
                changed_fields.append("acl_hash")
            if previous_state["permissions_json"] != dict(external_item.permissions_json or {}):
                changed_fields.append("permissions")
            if previous_state["deleted_at"] != external_item.deleted_at:
                changed_fields.append("deleted_at")
            if changed_fields:
                await self._audit(
                    session,
                    organization_id=organization_id,
                    user_id=None,
                    action=ConnectorAuditAction.source_permission_changed.value,
                    resource_type="external_item",
                    resource_id=external_item.id,
                    metadata={
                        "provider_key": item.provider_key,
                        "provider_item_id": item.provider_item_id,
                        "external_source_id": (
                            str(external_item.external_source_id)
                            if external_item.external_source_id
                            else None
                        ),
                        "collection_id": (
                            str(external_item.collection_id)
                            if external_item.collection_id
                            else None
                        ),
                        "changed_fields": changed_fields,
                        "permissions": sanitize_metadata(external_item.permissions_json),
                        "visibility": external_item.visibility,
                    },
                )
        return external_item

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

    async def _audit(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        metadata: dict[str, object],
    ) -> None:
        await self.audit_service.record(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=sanitize_metadata(metadata),
        )
