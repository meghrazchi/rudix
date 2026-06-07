from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, distinct, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.schemas.chat import SourceScopeRequest
from app.domains.collections.repositories.collections import CollectionRepository
from app.models.collection import CollectionDocument
from app.models.connector import (
    ConnectorConnection,
    ConnectorProvider,
    ExternalItem,
    ExternalSource,
)
from app.models.connector_source import SourceDocument
from app.models.document import Document
from app.models.enums import ConnectorConnectionStatus, DocumentStatus, OrganizationRole

_ADMIN_ROLES: frozenset[str] = frozenset(
    {OrganizationRole.owner.value, OrganizationRole.admin.value}
)


@dataclass(frozen=True)
class ResolvedSourceScope:
    document_ids: list[UUID] | None
    label: str | None = None


class SourceScopeService:
    """Resolve chat source-scope selections into accessible document IDs."""

    def __init__(self) -> None:
        self._collection_repository = CollectionRepository()

    async def resolve_document_ids(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        source_scope: SourceScopeRequest | None,
        explicit_document_ids: list[UUID] | None = None,
    ) -> ResolvedSourceScope:
        normalized_explicit_ids = self._unique_uuids(explicit_document_ids or [])
        if source_scope is None:
            return ResolvedSourceScope(
                document_ids=normalized_explicit_ids or None,
                label=None,
            )

        if source_scope.mode == "all" and not self._has_any_filters(source_scope):
            return ResolvedSourceScope(
                document_ids=normalized_explicit_ids or None,
                label="All sources",
            )

        scoped_ids = await self._document_ids_for_scope(
            session,
            organization_id=organization_id,
            user_id=user_id,
            user_roles=user_roles,
            source_scope=source_scope,
        )

        if scoped_ids is None:
            return ResolvedSourceScope(document_ids=normalized_explicit_ids or None, label=None)

        combined_ids = self._unique_uuids([*normalized_explicit_ids, *scoped_ids])
        return ResolvedSourceScope(
            document_ids=combined_ids,
            label=self._build_label(source_scope),
        )

    async def _document_ids_for_scope(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        source_scope: SourceScopeRequest,
    ) -> list[UUID] | None:
        # If no scoping filters are present, treat this as "all accessible indexed docs".
        if not self._has_any_filters(source_scope) and source_scope.mode == "all":
            return None

        if source_scope.mode == "collections" and not source_scope.collection_ids:
            return []

        connector_filter_requested = any(
            [
                source_scope.provider_keys,
                source_scope.connection_ids,
                source_scope.provider_source_ids,
                source_scope.external_source_ids,
                source_scope.external_item_ids,
            ]
        )
        if source_scope.mode in {"connector_sources", "connector_items"} and not (
            connector_filter_requested or source_scope.sync_statuses
        ):
            return []

        accessible_collection_ids = await self._accessible_collection_ids(
            session,
            organization_id=organization_id,
            user_id=user_id,
            user_roles=user_roles,
            collection_ids=source_scope.collection_ids,
        )
        if source_scope.collection_ids and not accessible_collection_ids:
            return []

        conditions = [Document.organization_id == organization_id]
        normalized_sync_statuses = {
            status.strip().lower() for status in source_scope.sync_statuses if status.strip()
        }
        needs_connector_joins = any(status != "uploaded" for status in normalized_sync_statuses)
        join_source_document = needs_connector_joins
        if source_scope.mode == "uploaded":
            conditions.append(Document.connector_external_item_id.is_(None))
        elif source_scope.mode in {"collections", "connector_sources", "connector_items"}:
            # Narrow via the filters below.
            pass

        if source_scope.document_types:
            conditions.append(Document.file_type.in_(source_scope.document_types))

        if source_scope.sync_statuses:
            source_status_clause = self._sync_status_clause(source_scope.sync_statuses)
            if source_status_clause is not None:
                conditions.append(source_status_clause)

        joins_needed = False
        item_filters: list[object] = []

        if (
            source_scope.provider_keys
            or source_scope.connection_ids
            or source_scope.provider_source_ids
            or source_scope.external_source_ids
            or source_scope.external_item_ids
            or source_scope.mode in {"connector_sources", "connector_items"}
            or needs_connector_joins
        ):
            joins_needed = True
            item_filters.append(Document.connector_external_item_id == ExternalItem.id)
            item_filters.append(ExternalItem.organization_id == organization_id)
            item_filters.append(ExternalItem.deleted_at.is_(None))
            item_filters.append(ConnectorConnection.id == ExternalItem.connection_id)
            item_filters.append(ConnectorConnection.organization_id == organization_id)
            item_filters.append(
                ConnectorConnection.status == ConnectorConnectionStatus.active.value
            )
            item_filters.append(ConnectorProvider.id == ConnectorConnection.provider_id)
            item_filters.append(ConnectorProvider.key.isnot(None))
            item_filters.append(SourceDocument.status == "active")
            if source_scope.provider_keys:
                item_filters.append(ConnectorProvider.key.in_(source_scope.provider_keys))
            if source_scope.connection_ids:
                connection_ids = self._parse_uuid_list(source_scope.connection_ids)
                if not connection_ids:
                    return []
                item_filters.append(ExternalItem.connection_id.in_(connection_ids))
            if source_scope.provider_source_ids:
                provider_source_ids = self._parse_string_list(source_scope.provider_source_ids)
                if not provider_source_ids:
                    return []
                item_filters.append(ExternalSource.provider_source_id.in_(provider_source_ids))
            if source_scope.external_source_ids:
                source_ids = self._parse_uuid_list(source_scope.external_source_ids)
                if not source_ids:
                    return []
                item_filters.append(ExternalItem.external_source_id.in_(source_ids))
            if source_scope.external_item_ids:
                item_ids = self._parse_uuid_list(source_scope.external_item_ids)
                if not item_ids:
                    return []
                item_filters.append(ExternalItem.id.in_(item_ids))

        statement = select(distinct(Document.id)).where(*conditions)

        if accessible_collection_ids:
            statement = statement.join(
                CollectionDocument, CollectionDocument.document_id == Document.id
            ).where(CollectionDocument.collection_id.in_(accessible_collection_ids))

        if joins_needed:
            join_source_document = True
            statement = (
                statement.join(ExternalItem, ExternalItem.id == Document.connector_external_item_id)
                .join(ConnectorConnection, ConnectorConnection.id == ExternalItem.connection_id)
                .join(ConnectorProvider, ConnectorProvider.id == ConnectorConnection.provider_id)
            )
            if source_scope.provider_source_ids or source_scope.external_source_ids:
                statement = statement.join(
                    ExternalSource, ExternalSource.id == ExternalItem.external_source_id
                )
            statement = statement.where(*item_filters)

        if join_source_document:
            statement = statement.join(SourceDocument, SourceDocument.document_id == Document.id)

        statement = statement.where(Document.status == DocumentStatus.indexed.value)
        result = await session.execute(statement)
        document_ids = [UUID(str(row[0])) for row in result.all()]
        return self._unique_uuids(document_ids)

    async def _accessible_collection_ids(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        collection_ids: list[str],
    ) -> list[UUID]:
        if not collection_ids:
            return []
        if _ADMIN_ROLES.intersection({role.strip() for role in user_roles if role.strip()}):
            return [
                UUID(collection_id)
                for collection_id in collection_ids
                if self._is_uuid(collection_id)
            ]

        accessible: list[UUID] = []
        for raw_id in collection_ids:
            if not self._is_uuid(raw_id):
                continue
            collection = await self._collection_repository.get(
                session,
                collection_id=UUID(raw_id),
                organization_id=organization_id,
                user_id=user_id,
                user_roles=user_roles,
            )
            if collection is not None:
                accessible.append(collection.id)
        return accessible

    @staticmethod
    def _sync_status_clause(sync_statuses: list[str]):
        normalized = {status.strip().lower() for status in sync_statuses if status.strip()}
        if not normalized:
            return None
        if normalized == {"uploaded"}:
            return Document.connector_external_item_id.is_(None)
        if normalized == {"active"}:
            return and_(
                Document.connector_external_item_id.is_not(None),
                ExternalItem.deleted_at.is_(None),
                ConnectorConnection.status == ConnectorConnectionStatus.active.value,
                SourceDocument.status == "active",
            )
        if normalized == {"deleted"}:
            return or_(
                ExternalItem.deleted_at.is_not(None),
                ConnectorConnection.status != ConnectorConnectionStatus.active.value,
                SourceDocument.status != "active",
            )
        if normalized == {"revoked"}:
            return ConnectorConnection.status != ConnectorConnectionStatus.active.value
        if normalized == {"stale"}:
            return and_(
                ExternalItem.deleted_at.is_(None),
                ConnectorConnection.status == ConnectorConnectionStatus.active.value,
                SourceDocument.status == "active",
                SourceDocument.sync_version != ExternalItem.sync_version,
            )
        return None

    @staticmethod
    def _has_any_filters(source_scope: SourceScopeRequest) -> bool:
        return any(
            [
                source_scope.provider_keys,
                source_scope.connection_ids,
                source_scope.external_source_ids,
                source_scope.external_item_ids,
                source_scope.collection_ids,
                source_scope.document_types,
                source_scope.sync_statuses,
                source_scope.mode != "all",
            ]
        )

    @staticmethod
    def _build_label(source_scope: SourceScopeRequest) -> str | None:
        parts: list[str] = []
        if source_scope.mode != "all":
            parts.append(source_scope.mode.replace("_", " ").title())
        if source_scope.provider_keys:
            parts.append(", ".join(source_scope.provider_keys[:2]))
        elif source_scope.provider_source_ids:
            parts.append(", ".join(source_scope.provider_source_ids[:2]))
        elif source_scope.connection_ids:
            parts.append(f"{len(source_scope.connection_ids)} connection(s)")
        elif source_scope.external_source_ids:
            parts.append(f"{len(source_scope.external_source_ids)} source(s)")
        elif source_scope.external_item_ids:
            parts.append(f"{len(source_scope.external_item_ids)} item(s)")
        elif source_scope.collection_ids:
            parts.append(f"{len(source_scope.collection_ids)} collection(s)")
        if not parts:
            return None
        return " · ".join(parts)

    @staticmethod
    def _unique_uuids(values: list[UUID]) -> list[UUID]:
        seen: set[str] = set()
        unique: list[UUID] = []
        for value in values:
            key = str(value)
            if key in seen:
                continue
            seen.add(key)
            unique.append(value)
        return unique

    @staticmethod
    def _is_uuid(value: str) -> bool:
        try:
            UUID(value)
        except ValueError:
            return False
        return True

    @staticmethod
    def _parse_uuid_list(values: list[str]) -> list[UUID]:
        parsed: list[UUID] = []
        for value in values:
            if not SourceScopeService._is_uuid(value):
                continue
            parsed.append(UUID(value))
        return SourceScopeService._unique_uuids(parsed)

    @staticmethod
    def _parse_string_list(values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            trimmed = value.strip()
            if not trimmed or trimmed in seen:
                continue
            seen.add(trimmed)
            normalized.append(trimmed)
        return normalized
