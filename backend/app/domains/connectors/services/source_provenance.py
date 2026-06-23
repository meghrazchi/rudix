from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.connector_source import SourceDocument, SourceReference
from app.models.document import Document
from app.models.enums import ConnectorConnectionStatus


@dataclass(frozen=True)
class SourceCitationDetails:
    connector_connection_id: UUID | None
    provider_key: str | None
    provider_label: str | None
    source_title: str | None
    source_key: str | None
    source_section: str | None
    source_deep_link: str | None
    source_last_synced_at: datetime | None
    source_trust_status: str
    source_content_hash: str | None
    source_sync_version: int | None
    source_acl_snapshot: dict[str, Any]
    source_visibility: str | None


class SourceProvenanceService:
    """Loads and filters connector-backed source provenance for citations."""

    @staticmethod
    def build_locator_snapshot(
        *,
        provider_key: str,
        item_type: str,
        provider_item_id: str,
        source_url: str,
        section_label: str | None = None,
        page_number: int | None = None,
        comment_id: str | None = None,
        attachment_id: str | None = None,
        field_name: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "provider_key": provider_key,
            "item_type": item_type,
            "provider_item_id": provider_item_id,
            "source_url": source_url,
            "source_section": section_label,
            "page_number": page_number,
            "comment_id": comment_id,
            "attachment_id": attachment_id,
            "field_name": field_name,
            "folder_id": folder_id,
        }

    @staticmethod
    def build_metadata_snapshot(
        *,
        provider_key: str,
        provider_label: str | None,
        source_title: str,
        source_key: str,
        source_url: str,
        source_section: str | None,
        content_hash: str,
        sync_version: int,
        last_synced_at: datetime | None,
        trust_status: str,
        acl_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "provider_key": provider_key,
            "provider_label": provider_label,
            "source_title": source_title,
            "source_key": source_key,
            "source_url": source_url,
            "source_section": source_section,
            "content_hash": content_hash,
            "sync_version": sync_version,
            "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
            "trust_status": trust_status,
            "acl_snapshot": acl_snapshot or {},
        }

    @staticmethod
    def build_source_label(
        *,
        provider_label: str | None,
        source_title: str | None,
        source_key: str | None,
    ) -> str | None:
        parts = [
            part.strip()
            for part in (provider_label, source_title, source_key)
            if part and part.strip()
        ]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return f"{parts[0]} · {parts[1]}"
        return f"{parts[0]} · {parts[1]} ({parts[2]})"

    async def filter_active_chunks(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        chunks: list[Any],
    ) -> list[Any]:
        if not chunks:
            return []

        document_ids = [
            document_id
            for document_id in {getattr(chunk, "document_id", None) for chunk in chunks}
            if isinstance(document_id, UUID)
        ]
        if not document_ids:
            return chunks

        active_documents = await self._active_document_ids(
            session,
            organization_id=organization_id,
            document_ids=document_ids,
        )
        if not active_documents:
            return []

        active_document_set = {str(document_id) for document_id in active_documents}
        filtered_chunks = [
            chunk
            for chunk in chunks
            if str(getattr(chunk, "document_id", "")) in active_document_set
        ]
        return filtered_chunks

    async def load_citation_details(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        chunk_ids: list[UUID],
    ) -> dict[UUID, SourceCitationDetails]:
        if not chunk_ids:
            return {}

        provider_alias = aliased(ConnectorProvider)
        connection_alias = aliased(ConnectorConnection)
        statement = (
            select(
                SourceReference.chunk_id,
                SourceReference.locator_json,
                SourceReference.metadata_json,
                SourceReference.source_url,
                SourceReference.title,
                SourceDocument.updated_at,
                SourceDocument.content_hash,
                SourceDocument.sync_version,
                SourceDocument.status,
                ExternalItem.connection_id,
                ExternalItem.provider_item_id,
                ExternalItem.title,
                ExternalItem.source_url,
                ExternalItem.deleted_at,
                ExternalItem.content_hash,
                ExternalItem.sync_version,
                ExternalItem.permissions_json,
                ExternalItem.visibility,
                provider_alias.key,
                provider_alias.display_name,
                connection_alias.status,
            )
            .join(SourceDocument, SourceDocument.id == SourceReference.source_document_id)
            .join(ExternalItem, ExternalItem.id == SourceReference.external_item_id)
            .join(connection_alias, connection_alias.id == ExternalItem.connection_id)
            .join(provider_alias, provider_alias.id == connection_alias.provider_id)
            .where(SourceReference.chunk_id.in_(chunk_ids))
            .where(SourceReference.organization_id == organization_id)
        )
        rows = (await session.execute(statement)).all()

        details_by_chunk_id: dict[UUID, SourceCitationDetails] = {}
        for row in rows:
            chunk_id = row[0]
            if chunk_id is None:
                continue
            locator = row[1] or {}
            metadata = row[2] or {}
            source_url = row[3] or row[12]
            source_title = row[4] or row[11]
            trust_status = self._trust_status(
                connection_status=str(row[20] or ""),
                deleted_at=row[13],
                source_document_status=str(row[8] or ""),
                source_document_content_hash=str(row[6] or ""),
                source_document_sync_version=row[7],
                external_item_content_hash=str(row[14] or ""),
                external_item_sync_version=row[15],
                metadata=metadata,
            )
            details_by_chunk_id[chunk_id] = SourceCitationDetails(
                connector_connection_id=row[9],
                provider_key=str(row[18] or "").strip() or None,
                provider_label=str(row[19] or "").strip() or None,
                source_title=str(source_title or "").strip() or None,
                source_key=str(row[10] or "").strip() or None,
                source_section=self._source_section(locator=locator, metadata=metadata),
                source_deep_link=str(source_url or "").strip() or None,
                source_last_synced_at=row[5],
                source_trust_status=trust_status,
                source_content_hash=str(row[6] or "").strip() or None,
                source_sync_version=int(row[7]) if row[7] is not None else None,
                source_acl_snapshot=row[16] or {},
                source_visibility=str(row[17] or "").strip() or None,
            )

        return details_by_chunk_id

    async def load_citation_details_for_documents(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        document_ids: list[UUID],
    ) -> dict[UUID, SourceCitationDetails]:
        if not document_ids:
            return {}

        provider_alias = aliased(ConnectorProvider)
        connection_alias = aliased(ConnectorConnection)
        statement = (
            select(
                Document.id,
                SourceReference.locator_json,
                SourceReference.metadata_json,
                SourceReference.source_url,
                SourceReference.title,
                SourceDocument.updated_at,
                SourceDocument.content_hash,
                SourceDocument.sync_version,
                SourceDocument.status,
                ExternalItem.connection_id,
                ExternalItem.provider_item_id,
                ExternalItem.title,
                ExternalItem.source_url,
                ExternalItem.deleted_at,
                ExternalItem.content_hash,
                ExternalItem.sync_version,
                ExternalItem.permissions_json,
                ExternalItem.visibility,
                provider_alias.key,
                provider_alias.display_name,
                connection_alias.status,
            )
            .join(SourceDocument, SourceDocument.document_id == Document.id)
            .join(SourceReference, SourceReference.source_document_id == SourceDocument.id)
            .join(ExternalItem, ExternalItem.id == SourceReference.external_item_id)
            .join(connection_alias, connection_alias.id == ExternalItem.connection_id)
            .join(provider_alias, provider_alias.id == connection_alias.provider_id)
            .where(Document.id.in_(document_ids))
            .where(SourceReference.chunk_id.is_(None))
            .where(Document.organization_id == organization_id)
            .where(SourceDocument.organization_id == organization_id)
            .where(SourceReference.organization_id == organization_id)
            .where(ExternalItem.organization_id == organization_id)
            .where(connection_alias.organization_id == organization_id)
        )
        rows = (await session.execute(statement)).all()

        details_by_document_id: dict[UUID, SourceCitationDetails] = {}
        for row in rows:
            document_id = row[0]
            locator = row[1] or {}
            metadata = row[2] or {}
            source_url = row[3] or row[12]
            source_title = row[4] or row[11]
            trust_status = self._trust_status(
                connection_status=str(row[20] or ""),
                deleted_at=row[13],
                source_document_status=str(row[8] or ""),
                source_document_content_hash=str(row[6] or ""),
                source_document_sync_version=row[7],
                external_item_content_hash=str(row[14] or ""),
                external_item_sync_version=row[15],
                metadata=metadata,
            )
            details_by_document_id[document_id] = SourceCitationDetails(
                connector_connection_id=row[9],
                provider_key=str(row[18] or "").strip() or None,
                provider_label=str(row[19] or "").strip() or None,
                source_title=str(source_title or "").strip() or None,
                source_key=str(row[10] or "").strip() or None,
                source_section=self._source_section(locator=locator, metadata=metadata),
                source_deep_link=str(source_url or "").strip() or None,
                source_last_synced_at=row[5],
                source_trust_status=trust_status,
                source_content_hash=str(row[6] or "").strip() or None,
                source_sync_version=int(row[7]) if row[7] is not None else None,
                source_acl_snapshot=row[16] or {},
                source_visibility=str(row[17] or "").strip() or None,
            )

        return details_by_document_id

    async def _active_document_ids(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        document_ids: list[UUID],
    ) -> list[UUID]:
        statement = (
            select(Document.id)
            .select_from(Document)
            .join(SourceDocument, SourceDocument.document_id == Document.id, isouter=True)
            .join(ExternalItem, ExternalItem.id == SourceDocument.external_item_id, isouter=True)
            .join(
                ConnectorConnection,
                ConnectorConnection.id == ExternalItem.connection_id,
                isouter=True,
            )
            .where(Document.id.in_(document_ids))
            .where(Document.organization_id == organization_id)
            .where(
                (SourceDocument.id.is_(None))
                | (
                    (ExternalItem.deleted_at.is_(None))
                    & (ConnectorConnection.status == ConnectorConnectionStatus.active.value)
                )
            )
        )
        rows = await session.execute(statement)
        return [UUID(str(row[0])) for row in rows.all()]

    @staticmethod
    def _source_section(*, locator: dict[str, Any], metadata: dict[str, Any]) -> str | None:
        for key in (
            "source_section",
            "section_label",
            "section",
            "comment_id",
            "attachment_id",
            "field_name",
            "folder_id",
            "page_number",
        ):
            value = locator.get(key)
            if value is None:
                value = metadata.get(key)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                if key == "comment_id":
                    return f"Comment {normalized}"
                if key == "attachment_id":
                    return f"Attachment {normalized}"
                if key == "field_name":
                    return f"Field {normalized}"
                if key == "folder_id":
                    return f"Folder {normalized}"
                if key == "page_number":
                    return f"Page {normalized}"
                return normalized
        return None

    @staticmethod
    def _trust_status(
        *,
        connection_status: str,
        deleted_at: datetime | None,
        source_document_status: str,
        source_document_content_hash: str,
        source_document_sync_version: int | None,
        external_item_content_hash: str,
        external_item_sync_version: int | None,
        metadata: dict[str, Any],
    ) -> str:
        if deleted_at is not None:
            return "deleted"
        if connection_status and connection_status != ConnectorConnectionStatus.active.value:
            return "revoked"
        if source_document_status and source_document_status != "active":
            return "deleted"
        status = str(metadata.get("trust_status") or "").strip().lower()
        if status in {"deleted", "revoked"}:
            return status
        if status == "stale":
            return status
        if (
            source_document_sync_version is not None
            and external_item_sync_version is not None
            and source_document_sync_version != external_item_sync_version
        ):
            return "stale"
        source_item_content_hash = str(metadata.get("source_item_content_hash") or "").strip()
        if (
            source_item_content_hash
            and external_item_content_hash
            and source_item_content_hash != external_item_content_hash
        ):
            return "stale"
        return "trusted"
