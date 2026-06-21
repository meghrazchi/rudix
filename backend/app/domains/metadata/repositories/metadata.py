"""Repository layer for metadata fields and document metadata values (F256)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.metadata import DocumentMetadata, MetadataAuditLog, MetadataField


class MetadataFieldRepository:
    async def create(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        name: str,
        display_name: str,
        field_type: str,
        allowed_values: list[str] | None,
        is_required: bool,
        is_filterable: bool,
        description: str | None,
        sort_order: int,
    ) -> MetadataField:
        field = MetadataField(
            organization_id=organization_id,
            name=name,
            display_name=display_name,
            field_type=field_type,
            allowed_values=allowed_values,
            is_required=is_required,
            is_filterable=is_filterable,
            description=description,
            sort_order=sort_order,
        )
        db.add(field)
        await db.flush()
        return field

    async def get(
        self,
        db: AsyncSession,
        *,
        field_id: UUID,
        organization_id: UUID,
    ) -> MetadataField | None:
        stmt = select(MetadataField).where(
            MetadataField.id == field_id,
            MetadataField.organization_id == organization_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(
        self,
        db: AsyncSession,
        *,
        name: str,
        organization_id: UUID,
    ) -> MetadataField | None:
        stmt = select(MetadataField).where(
            MetadataField.name == name,
            MetadataField.organization_id == organization_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        include_inactive: bool = False,
    ) -> list[MetadataField]:
        stmt = select(MetadataField).where(MetadataField.organization_id == organization_id)
        if not include_inactive:
            stmt = stmt.where(MetadataField.is_active.is_(True))
        stmt = stmt.order_by(MetadataField.sort_order, MetadataField.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        include_inactive: bool = False,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(MetadataField)
            .where(MetadataField.organization_id == organization_id)
        )
        if not include_inactive:
            stmt = stmt.where(MetadataField.is_active.is_(True))
        result = await db.execute(stmt)
        return result.scalar_one()

    async def update(
        self,
        db: AsyncSession,
        field: MetadataField,
        *,
        display_name: str | None,
        allowed_values: list[str] | None,
        is_required: bool | None,
        is_filterable: bool | None,
        description: str | None,
        sort_order: int | None,
        is_active: bool | None,
    ) -> None:
        if display_name is not None:
            field.display_name = display_name
        if allowed_values is not None:
            field.allowed_values = allowed_values
        if is_required is not None:
            field.is_required = is_required
        if is_filterable is not None:
            field.is_filterable = is_filterable
        if description is not None:
            field.description = description
        if sort_order is not None:
            field.sort_order = sort_order
        if is_active is not None:
            field.is_active = is_active
        await db.flush()

    async def delete(self, db: AsyncSession, field: MetadataField) -> None:
        await db.delete(field)
        await db.flush()


class DocumentMetadataRepository:
    async def get_document_metadata(
        self,
        db: AsyncSession,
        *,
        document_id: UUID,
        organization_id: UUID,
    ) -> list[DocumentMetadata]:
        stmt = (
            select(DocumentMetadata)
            .options(selectinload(DocumentMetadata.field))
            .where(
                DocumentMetadata.document_id == document_id,
                DocumentMetadata.organization_id == organization_id,
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_value(
        self,
        db: AsyncSession,
        *,
        document_id: UUID,
        field_id: UUID,
    ) -> DocumentMetadata | None:
        stmt = select(DocumentMetadata).where(
            DocumentMetadata.document_id == document_id,
            DocumentMetadata.field_id == field_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_value(
        self,
        db: AsyncSession,
        *,
        document_id: UUID,
        field_id: UUID,
        organization_id: UUID,
        value_text: str | None,
        value_json: list | None,
    ) -> DocumentMetadata:
        existing = await self.get_value(db, document_id=document_id, field_id=field_id)
        if existing:
            existing.value_text = value_text
            existing.value_json = value_json
            await db.flush()
            return existing
        row = DocumentMetadata(
            document_id=document_id,
            field_id=field_id,
            organization_id=organization_id,
            value_text=value_text,
            value_json=value_json,
        )
        db.add(row)
        await db.flush()
        return row

    async def delete_value(
        self,
        db: AsyncSession,
        *,
        document_id: UUID,
        field_id: UUID,
    ) -> bool:
        existing = await self.get_value(db, document_id=document_id, field_id=field_id)
        if not existing:
            return False
        await db.delete(existing)
        await db.flush()
        return True

    async def list_documents_by_metadata(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        filters: list[dict],
    ) -> list[UUID]:
        """Return document IDs matching all given metadata filters (AND logic).

        Each filter dict: {"field_id": UUID, "value": str | list[str]}
        """
        if not filters:
            return []
        doc_sets: list[set[UUID]] = []
        for f in filters:
            fid = UUID(str(f["field_id"]))
            val = f["value"]
            stmt = select(DocumentMetadata.document_id).where(
                DocumentMetadata.field_id == fid,
                DocumentMetadata.organization_id == organization_id,
            )
            if isinstance(val, list):
                # For multi_select: value_text must be one of the requested values
                stmt = stmt.where(DocumentMetadata.value_text.in_(val))
            else:
                stmt = stmt.where(DocumentMetadata.value_text == str(val))
            result = await db.execute(stmt)
            doc_sets.append({r[0] for r in result.all()})

        if not doc_sets:
            return []
        intersection = doc_sets[0]
        for s in doc_sets[1:]:
            intersection &= s
        return list(intersection)

    async def write_audit(
        self,
        db: AsyncSession,
        *,
        document_id: UUID,
        field_id: UUID,
        organization_id: UUID,
        changed_by_id: UUID | None,
        old_value: str | None,
        new_value: str | None,
        action: str,
    ) -> None:
        db.add(
            MetadataAuditLog(
                document_id=document_id,
                field_id=field_id,
                organization_id=organization_id,
                changed_by_id=changed_by_id,
                old_value=old_value,
                new_value=new_value,
                action=action,
                created_at=datetime.now(UTC),
            )
        )
        await db.flush()

    async def list_audit(
        self,
        db: AsyncSession,
        *,
        document_id: UUID,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MetadataAuditLog]:
        stmt = (
            select(MetadataAuditLog)
            .where(
                MetadataAuditLog.document_id == document_id,
                MetadataAuditLog.organization_id == organization_id,
            )
            .order_by(MetadataAuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def count_audit(
        self,
        db: AsyncSession,
        *,
        document_id: UUID,
        organization_id: UUID,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(MetadataAuditLog)
            .where(
                MetadataAuditLog.document_id == document_id,
                MetadataAuditLog.organization_id == organization_id,
            )
        )
        result = await db.execute(stmt)
        return result.scalar_one()
