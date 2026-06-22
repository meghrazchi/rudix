"""HTTP interface — taxonomy field management and document metadata (F256).

Admin endpoints (require admin/owner role):
  GET    /admin/metadata/fields
  POST   /admin/metadata/fields
  GET    /admin/metadata/fields/{field_id}
  PATCH  /admin/metadata/fields/{field_id}
  DELETE /admin/metadata/fields/{field_id}

Document metadata endpoints (authenticated users):
  GET    /documents/{document_id}/metadata
  PUT    /documents/{document_id}/metadata
  GET    /admin/metadata/fields/{field_id}/suggest
  POST   /admin/metadata/bulk-set
  GET    /documents/{document_id}/metadata/audit
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.metadata.repositories.metadata import (
    DocumentMetadataRepository,
    MetadataFieldRepository,
)
from app.domains.metadata.schemas.metadata import (
    BulkSetMetadataRequest,
    BulkSetMetadataResponse,
    CreateMetadataFieldRequest,
    DocumentMetadataResponse,
    DocumentMetadataValueResponse,
    MetadataAuditEntryResponse,
    MetadataAuditListResponse,
    MetadataFieldListResponse,
    MetadataFieldResponse,
    SetDocumentMetadataRequest,
    TagSuggestionResponse,
    UpdateMetadataFieldRequest,
)
from app.domains.metadata.services.metadata_service import MetadataService
from app.models.enums import OrganizationRole
from app.models.metadata import MetadataField

router = APIRouter(tags=["metadata"])

_field_repo = MetadataFieldRepository()
_doc_repo = DocumentMetadataRepository()
_svc = MetadataService()

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)
_READ_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
    OrganizationRole.reviewer.value,
    OrganizationRole.developer.value,
)
_WRITE_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
)


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if not principal.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No active organization context"
        )
    return UUID(principal.organization_id)


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    return UUID(principal.user_id)


def _field_to_response(field: MetadataField) -> MetadataFieldResponse:
    return MetadataFieldResponse(
        field_id=str(field.id),
        organization_id=str(field.organization_id),
        name=field.name,
        display_name=field.display_name,
        field_type=field.field_type,  # type: ignore[arg-type]
        allowed_values=field.allowed_values,
        is_required=field.is_required,
        is_filterable=field.is_filterable,
        description=field.description,
        sort_order=field.sort_order,
        is_active=field.is_active,
        created_at=field.created_at,
        updated_at=field.updated_at,
    )


# ── Admin: taxonomy field CRUD ─────────────────────────────────────────────────


@router.get("/admin/metadata/fields", response_model=MetadataFieldListResponse)
async def list_metadata_fields(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    include_inactive: bool = Query(default=False),
) -> MetadataFieldListResponse:
    org_id = _org_id(principal)
    fields = await _field_repo.list_all(
        db, organization_id=org_id, include_inactive=include_inactive
    )
    total = await _field_repo.count(db, organization_id=org_id, include_inactive=include_inactive)
    return MetadataFieldListResponse(
        items=[_field_to_response(f) for f in fields],
        total=total,
    )


@router.post(
    "/admin/metadata/fields",
    response_model=MetadataFieldResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_metadata_field(
    payload: CreateMetadataFieldRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MetadataFieldResponse:
    org_id = _org_id(principal)
    existing = await _field_repo.get_by_name(db, name=payload.name, organization_id=org_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A metadata field named '{payload.name}' already exists",
        )
    field = await _field_repo.create(
        db,
        organization_id=org_id,
        name=payload.name,
        display_name=payload.display_name,
        field_type=payload.field_type,
        allowed_values=payload.allowed_values,
        is_required=payload.is_required,
        is_filterable=payload.is_filterable,
        description=payload.description,
        sort_order=payload.sort_order,
    )
    await db.commit()
    await db.refresh(field)
    return _field_to_response(field)


@router.get(
    "/admin/metadata/fields/{field_id}",
    response_model=MetadataFieldResponse,
)
async def get_metadata_field(
    field_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MetadataFieldResponse:
    org_id = _org_id(principal)
    field = await _field_repo.get(db, field_id=field_id, organization_id=org_id)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metadata field not found"
        )
    return _field_to_response(field)


@router.patch(
    "/admin/metadata/fields/{field_id}",
    response_model=MetadataFieldResponse,
)
async def update_metadata_field(
    field_id: UUID,
    payload: UpdateMetadataFieldRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> MetadataFieldResponse:
    org_id = _org_id(principal)
    field = await _field_repo.get(db, field_id=field_id, organization_id=org_id)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metadata field not found"
        )
    if payload.allowed_values is not None and field.field_type not in ("select", "multi_select"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="allowed_values is only valid for select/multi_select fields",
        )
    await _field_repo.update(
        db,
        field,
        display_name=payload.display_name,
        allowed_values=payload.allowed_values,
        is_required=payload.is_required,
        is_filterable=payload.is_filterable,
        description=payload.description,
        sort_order=payload.sort_order,
        is_active=payload.is_active,
    )
    await db.commit()
    await db.refresh(field)
    return _field_to_response(field)


@router.delete(
    "/admin/metadata/fields/{field_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_metadata_field(
    field_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    org_id = _org_id(principal)
    field = await _field_repo.get(db, field_id=field_id, organization_id=org_id)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metadata field not found"
        )
    await _field_repo.delete(db, field)
    await db.commit()


# ── Tag suggestion ─────────────────────────────────────────────────────────────


@router.get(
    "/admin/metadata/fields/{field_id}/suggest",
    response_model=TagSuggestionResponse,
)
async def suggest_tag_values(
    field_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    prefix: str = Query(default="", max_length=128),
) -> TagSuggestionResponse:
    org_id = _org_id(principal)
    field = await _field_repo.get(db, field_id=field_id, organization_id=org_id)
    if not field or not field.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metadata field not found"
        )
    suggestions = _svc.build_tag_suggestions(field, prefix)
    return TagSuggestionResponse(
        field_id=str(field_id),
        prefix=prefix,
        suggestions=suggestions,
    )


# ── Document metadata CRUD ─────────────────────────────────────────────────────


@router.get(
    "/documents/{document_id}/metadata",
    response_model=DocumentMetadataResponse,
)
async def get_document_metadata(
    document_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentMetadataResponse:
    org_id = _org_id(principal)
    rows = await _doc_repo.get_document_metadata(
        db, document_id=document_id, organization_id=org_id
    )
    values = [
        DocumentMetadataValueResponse(
            field_id=str(row.field_id),
            field_name=row.field.name,
            display_name=row.field.display_name,
            field_type=row.field.field_type,  # type: ignore[arg-type]
            value=_svc.deserialize(row),
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return DocumentMetadataResponse(document_id=str(document_id), values=values)


@router.put(
    "/documents/{document_id}/metadata",
    response_model=DocumentMetadataResponse,
)
async def set_document_metadata(
    document_id: UUID,
    payload: SetDocumentMetadataRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_WRITE_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentMetadataResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)

    entries = [{"field_id": v.field_id, "value": v.value} for v in payload.values]
    await _svc.validate_and_save_document_values(
        db,
        document_id=document_id,
        organization_id=org_id,
        values=entries,
        changed_by_id=user_id,
        action="set",
    )
    await db.commit()

    rows = await _doc_repo.get_document_metadata(
        db, document_id=document_id, organization_id=org_id
    )
    values_resp = [
        DocumentMetadataValueResponse(
            field_id=str(row.field_id),
            field_name=row.field.name,
            display_name=row.field.display_name,
            field_type=row.field.field_type,  # type: ignore[arg-type]
            value=_svc.deserialize(row),
            updated_at=row.updated_at,
        )
        for row in rows
    ]
    return DocumentMetadataResponse(document_id=str(document_id), values=values_resp)


# ── Bulk set ───────────────────────────────────────────────────────────────────


@router.post(
    "/admin/metadata/bulk-set",
    response_model=BulkSetMetadataResponse,
)
async def bulk_set_metadata(
    payload: BulkSetMetadataRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> BulkSetMetadataResponse:
    org_id = _org_id(principal)
    user_id = _user_id(principal)
    entries = [{"field_id": v.field_id, "value": v.value} for v in payload.values]

    updated = 0
    skipped = 0
    errors: list[str] = []

    for doc_id_str in payload.document_ids:
        try:
            doc_id = UUID(doc_id_str)
        except ValueError:
            errors.append(f"Invalid document_id: {doc_id_str}")
            skipped += 1
            continue
        try:
            await _svc.validate_and_save_document_values(
                db,
                document_id=doc_id,
                organization_id=org_id,
                values=entries,
                changed_by_id=user_id,
                action="bulk_set",
            )
            updated += 1
        except HTTPException as exc:
            errors.append(f"[{doc_id_str}] {exc.detail}")
            skipped += 1

    await db.commit()
    return BulkSetMetadataResponse(updated=updated, skipped=skipped, errors=errors)


# ── Metadata audit log ─────────────────────────────────────────────────────────


@router.get(
    "/admin/metadata/filter-documents",
    response_model=dict,
)
async def filter_documents_by_metadata(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_READ_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    filters: Annotated[
        list[str] | None,
        Query(
            alias="filter",
            description="Repeated param: field_id:value",
            max_length=50,
        ),
    ] = None,
) -> dict:
    """Return document IDs that satisfy ALL provided metadata filters.

    Each `filter` param is `<field_id>:<value>`.  AND logic across all entries.
    """
    org_id = _org_id(principal)
    parsed: list[dict] = []
    for raw in filters or []:
        if ":" not in raw:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid filter format '{raw}'. Expected 'field_id:value'.",
            )
        field_id_str, value = raw.split(":", 1)
        parsed.append({"field_id": field_id_str.strip(), "value": value})
    if not parsed:
        return {"document_ids": []}
    doc_ids = await _doc_repo.list_documents_by_metadata(db, organization_id=org_id, filters=parsed)
    return {"document_ids": [str(d) for d in doc_ids]}


@router.get(
    "/documents/{document_id}/metadata/audit",
    response_model=MetadataAuditListResponse,
)
async def get_metadata_audit(
    document_id: UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MetadataAuditListResponse:
    org_id = _org_id(principal)

    # Fetch field names for display
    fields = await _field_repo.list_all(db, organization_id=org_id, include_inactive=True)
    field_name_map = {f.id: f.name for f in fields}

    logs = await _doc_repo.list_audit(
        db, document_id=document_id, organization_id=org_id, limit=limit, offset=offset
    )
    total = await _doc_repo.count_audit(db, document_id=document_id, organization_id=org_id)
    return MetadataAuditListResponse(
        items=[
            MetadataAuditEntryResponse(
                audit_id=str(log.id),
                document_id=str(log.document_id),
                field_id=str(log.field_id),
                field_name=field_name_map.get(log.field_id, str(log.field_id)),
                changed_by_id=str(log.changed_by_id) if log.changed_by_id else None,
                old_value=log.old_value,
                new_value=log.new_value,
                action=log.action,  # type: ignore[arg-type]
                created_at=log.created_at,
            )
            for log in logs
        ],
        total=total,
    )
