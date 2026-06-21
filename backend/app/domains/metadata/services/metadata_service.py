"""Business logic for taxonomy fields and document metadata (F256)."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.metadata.repositories.metadata import (
    DocumentMetadataRepository,
    MetadataFieldRepository,
)
from app.models.metadata import DocumentMetadata, MetadataField


_field_repo = MetadataFieldRepository()
_doc_repo = DocumentMetadataRepository()

# ─── Field type ↔ value coercions ────────────────────────────────────────────

_REQUIRES_ALLOWED = {"select", "multi_select"}


def _serialize_value(field: MetadataField, value: object) -> tuple[str | None, list | None]:
    """Return (value_text, value_json) for storage."""
    ft = field.field_type
    if value is None:
        return None, None
    if ft == "multi_select":
        if not isinstance(value, list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{field.name}' expects a list of strings for multi_select",
            )
        for v in value:
            _validate_allowed(field, str(v))
        return None, [str(v) for v in value]
    if ft == "select":
        _validate_allowed(field, str(value))
        return str(value), None
    if ft == "boolean":
        if not isinstance(value, bool):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{field.name}' expects a boolean value",
            )
        return str(value).lower(), None
    if ft == "number":
        try:
            float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Field '{field.name}' expects a numeric value",
            )
        return str(value), None
    # text / date — store as text
    return str(value), None


def _deserialize_value(row: DocumentMetadata) -> object:
    ft = row.field.field_type
    if ft == "multi_select":
        return row.value_json or []
    if ft == "boolean":
        if row.value_text is None:
            return None
        return row.value_text.lower() == "true"
    if ft == "number":
        if row.value_text is None:
            return None
        try:
            f = float(row.value_text)
            return int(f) if f == int(f) else f
        except (TypeError, ValueError):
            return row.value_text
    return row.value_text


def _validate_allowed(field: MetadataField, value: str) -> None:
    if field.field_type in _REQUIRES_ALLOWED and field.allowed_values:
        if value not in field.allowed_values:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Value '{value}' is not in the allowed values for field '{field.name}'. "
                    f"Allowed: {field.allowed_values}"
                ),
            )


# ─── Service façade ───────────────────────────────────────────────────────────


class MetadataService:

    async def validate_and_save_document_values(
        self,
        db: AsyncSession,
        *,
        document_id: UUID,
        organization_id: UUID,
        values: list[dict],
        changed_by_id: UUID | None,
        action: str = "set",
    ) -> list[DocumentMetadata]:
        """Validate and upsert metadata values for a document.

        `values` is a list of {"field_id": str, "value": Any}.
        Raises HTTPException on validation failure.
        """
        results: list[DocumentMetadata] = []
        for entry in values:
            field_id = UUID(entry["field_id"])
            value = entry.get("value")

            field = await _field_repo.get(db, field_id=field_id, organization_id=organization_id)
            if field is None or not field.is_active:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Metadata field '{entry['field_id']}' not found",
                )

            # Fetch old value for audit
            existing = await _doc_repo.get_value(
                db, document_id=document_id, field_id=field_id
            )
            old_text = existing.value_text if existing else None
            old_json = existing.value_json if existing else None

            value_text, value_json = _serialize_value(field, value)

            row = await _doc_repo.upsert_value(
                db,
                document_id=document_id,
                field_id=field_id,
                organization_id=organization_id,
                value_text=value_text,
                value_json=value_json,
            )
            results.append(row)

            old_repr = (
                json.dumps(old_json) if old_json is not None else old_text
            )
            new_repr = (
                json.dumps(value_json) if value_json is not None else value_text
            )
            await _doc_repo.write_audit(
                db,
                document_id=document_id,
                field_id=field_id,
                organization_id=organization_id,
                changed_by_id=changed_by_id,
                old_value=old_repr,
                new_value=new_repr,
                action=action,
            )

        return results

    def check_required_fields(
        self,
        fields: list[MetadataField],
        values: list[DocumentMetadata],
    ) -> list[str]:
        """Return list of required field names that are missing a value."""
        provided_ids = {row.field_id for row in values}
        missing = []
        for field in fields:
            if field.is_required and field.id not in provided_ids:
                missing.append(field.name)
        return missing

    def build_tag_suggestions(
        self,
        field: MetadataField,
        prefix: str,
        limit: int = 20,
    ) -> list[str]:
        """Return allowed_values that start with prefix for select/multi_select fields."""
        if field.field_type not in ("select", "multi_select") or not field.allowed_values:
            return []
        prefix_lower = prefix.lower()
        return [
            v for v in field.allowed_values if v.lower().startswith(prefix_lower)
        ][:limit]

    def deserialize(self, row: DocumentMetadata) -> object:
        return _deserialize_value(row)
