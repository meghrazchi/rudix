from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.documents.workflows import retry_delete_document_workflow
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.schemas.documents import (
    ALLOWED_LANGUAGES,
    AdminDocumentDeletionItem,
    AdminDocumentDeletionListResponse,
    RetryDeleteDocumentResponse,
)
from app.models.document import Document
from app.models.enums import (
    DocumentQualityState,
    DocumentReviewStatus,
    DocumentStatus,
    DocumentTrustStatus,
    OcrQualityStatus,
    OrganizationRole,
)
from app.models.user import User
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.workers.document_tasks import delete_document as delete_document_task
from app.workers.document_tasks import reindex_document as reindex_document_task

_ALLOWED_TRUST_STATUSES = frozenset(s.value for s in DocumentTrustStatus)
_ALLOWED_REVIEW_STATUSES = frozenset(s.value for s in DocumentReviewStatus)
_ALLOWED_QUALITY_STATES = frozenset(s.value for s in DocumentQualityState)


class AdminLanguageOverrideRequest(BaseModel):
    language: str | None = None

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_LANGUAGES:
            raise ValueError(f"Unsupported language code: {value}")
        return value


class AdminLanguageOverrideResponse(BaseModel):
    document_id: str
    language: str | None
    language_source: str | None
    language_confidence: float | None
    updated_at: datetime


class AdminOcrConfigRequest(BaseModel):
    ocr_languages: list[str] | None = None

    @field_validator("ocr_languages")
    @classmethod
    def validate_ocr_languages(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        from app.domains.documents.services.ocr_language_config import (
            UnsupportedOcrLanguageError,
            validate_iso_languages,
        )

        try:
            return validate_iso_languages(value)
        except UnsupportedOcrLanguageError as exc:
            raise ValueError(str(exc)) from exc


class AdminOcrConfigResponse(BaseModel):
    document_id: str
    ocr_languages_override: str | None
    ocr_quality_snapshot: dict | None
    updated_at: datetime


class AdminTrustStatusRequest(BaseModel):
    trust_status: str
    quality_state: str | None = None
    quality_notes: str | None = None
    quality_owner_id: str | None = None
    quality_reviewer_id: str | None = None
    review_status: str | None = None
    review_owner_id: str | None = None
    review_due_date: date | None = None
    expiry_date: date | None = None
    trust_level: str | None = None
    version_label: str | None = None
    review_date: date | None = None
    effective_date: date | None = None
    stale_after_days: int | None = None
    superseded_by_document_id: str | None = None

    @field_validator("trust_status")
    @classmethod
    def validate_trust_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_TRUST_STATUSES:
            raise ValueError(
                f"Invalid trust_status '{value}'. Must be one of: {sorted(_ALLOWED_TRUST_STATUSES)}"
            )
        return normalized

    @field_validator("stale_after_days")
    @classmethod
    def validate_stale_after_days(cls, value: int | None) -> int | None:
        if value is not None and (value < 1 or value > 3650):
            raise ValueError("stale_after_days must be between 1 and 3650")
        return value

    @field_validator("review_status")
    @classmethod
    def validate_review_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_REVIEW_STATUSES:
            raise ValueError(
                f"Invalid review_status '{value}'. Must be one of: {sorted(_ALLOWED_REVIEW_STATUSES)}"
            )
        return normalized

    @field_validator("quality_state")
    @classmethod
    def validate_quality_state(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in _ALLOWED_QUALITY_STATES:
            raise ValueError(
                f"Invalid quality_state '{value}'. Must be one of: {sorted(_ALLOWED_QUALITY_STATES)}"
            )
        return normalized


class AdminTrustStatusResponse(BaseModel):
    document_id: str
    trust_status: str
    quality_state: str | None
    quality_notes: str | None
    quality_owner_id: str | None
    quality_reviewer_id: str | None
    review_status: str
    review_owner_id: str | None
    review_due_date: date | None
    expiry_date: date | None
    trust_level: str | None
    version_label: str | None
    review_date: date | None
    effective_date: date | None
    stale_after_days: int | None
    superseded_by_document_id: str | None
    trusted_at: datetime | None
    updated_at: datetime


class BulkAdminTrustStatusRequest(AdminTrustStatusRequest):
    document_ids: list[str] = Field(min_length=1, max_length=500)

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("document_ids must not be empty")
        return cleaned


class BulkAdminTrustStatusResult(BaseModel):
    document_id: str
    status: Literal["updated", "skipped", "error"]
    error: str | None = None


class BulkAdminTrustStatusResponse(BaseModel):
    updated: int
    skipped: int
    errors: list[str]
    results: list[BulkAdminTrustStatusResult]


class AdminOcrRetryResponse(BaseModel):
    document_id: str
    ocr_quality_status: str | None
    ocr_avg_confidence: float | None
    queue_status: Literal["queued"]


router = APIRouter(prefix="/admin/documents", tags=["admin"])

document_repository = DocumentRepository()
audit_log_service = AuditLogService()

_DELETION_STATUSES = [
    DocumentStatus.delete_requested.value,
    DocumentStatus.deleting.value,
    DocumentStatus.retained_by_policy.value,
]


def _organization_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc


def _principal_user_and_org(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.user_id), UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc


async def _resolve_reviewer_id(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    reviewer_id: str | None,
) -> UUID | None:
    if reviewer_id is None:
        return None
    try:
        parsed = UUID(reviewer_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid review_owner_id format",
        ) from exc
    result = await db_session.execute(
        select(User.id).where(
            User.id == parsed,
            User.organization_id == organization_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="review_owner_id must reference a user in the active organization",
        )
    return parsed


async def _update_document_trust_status_for_payload(
    *,
    db_session: AsyncSession,
    actor_user_id: UUID,
    actor_organization_id: UUID,
    request_id: str | None,
    document_id: UUID,
    payload: AdminTrustStatusRequest,
) -> Document:
    document = await document_repository.get_document_by_id(db_session, document_id=document_id)
    if document is None or document.organization_id != actor_organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    superseded_by_uuid: UUID | None = None
    if payload.superseded_by_document_id is not None:
        try:
            superseded_by_uuid = UUID(payload.superseded_by_document_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid superseded_by_document_id format",
            ) from exc
        successor = await document_repository.get_document_by_id(
            db_session, document_id=superseded_by_uuid
        )
        if successor is None or successor.organization_id != actor_organization_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="superseded_by_document_id refers to a document that does not exist",
            )

    review_owner_uuid = await _resolve_reviewer_id(
        db_session,
        organization_id=actor_organization_id,
        reviewer_id=payload.review_owner_id,
    )
    quality_owner_uuid = await _resolve_reviewer_id(
        db_session,
        organization_id=actor_organization_id,
        reviewer_id=payload.quality_owner_id,
    )
    quality_reviewer_uuid = await _resolve_reviewer_id(
        db_session,
        organization_id=actor_organization_id,
        reviewer_id=payload.quality_reviewer_id,
    )

    now = datetime.now(UTC)
    trusted_at = now if payload.trust_status == DocumentTrustStatus.verified.value else None
    trusted_by_id = (
        actor_user_id if payload.trust_status == DocumentTrustStatus.verified.value else None
    )
    quality_trust_status = payload.trust_status
    quality_review_status = payload.review_status
    quality_review_date = payload.review_date
    quality_trusted_at = trusted_at
    quality_trusted_by_id = trusted_by_id

    mapped_quality_status, mapped_review_status, mapped_trusted_at, mapped_trusted_by_id = (
        _quality_to_legacy_values(
            payload.quality_state,
            actor_user_id=actor_user_id,
            quality_reviewer_id=quality_reviewer_uuid,
        )
    )
    if mapped_quality_status is not None:
        quality_trust_status = mapped_quality_status
    if mapped_review_status is not None:
        quality_review_status = mapped_review_status
    if mapped_trusted_at is not None or payload.quality_state is not None:
        quality_trusted_at = mapped_trusted_at
    if mapped_trusted_by_id is not None or payload.quality_state is not None:
        quality_trusted_by_id = mapped_trusted_by_id
    effective_review_owner_uuid = quality_owner_uuid or review_owner_uuid

    updated = await document_repository.update_document_trust_status(
        db_session,
        document_id=document_id,
        trust_status=quality_trust_status,
        review_status=quality_review_status,
        review_owner_id=effective_review_owner_uuid,
        review_due_date=payload.review_due_date,
        expiry_date=payload.expiry_date,
        trust_level=payload.trust_level,
        quality_state=payload.quality_state,
        quality_notes=payload.quality_notes,
        version_label=payload.version_label,
        review_date=quality_review_date,
        effective_date=payload.effective_date,
        stale_after_days=payload.stale_after_days,
        superseded_by_document_id=superseded_by_uuid,
        trusted_at=quality_trusted_at,
        trusted_by_id=quality_trusted_by_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.trust_status.updated",
        resource_type="document",
        resource_id=document_id,
        request_id=request_id,
        metadata={
            "trust_status": payload.trust_status,
            "quality_state": payload.quality_state,
            "quality_notes": payload.quality_notes,
            "quality_owner_id": payload.quality_owner_id,
            "quality_reviewer_id": payload.quality_reviewer_id,
            "review_status": payload.review_status,
            "review_owner_id": payload.review_owner_id,
            "review_due_date": payload.review_due_date.isoformat()
            if payload.review_due_date
            else None,
            "expiry_date": payload.expiry_date.isoformat() if payload.expiry_date else None,
            "trust_level": payload.trust_level,
            "version_label": payload.version_label,
            "review_date": payload.review_date.isoformat() if payload.review_date else None,
            "effective_date": payload.effective_date.isoformat()
            if payload.effective_date
            else None,
            "stale_after_days": payload.stale_after_days,
            "superseded_by_document_id": payload.superseded_by_document_id,
        },
    )
    return updated


def _request_id_from_request(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")


def _quality_to_legacy_values(
    quality_state: str | None,
    *,
    actor_user_id: UUID,
    quality_reviewer_id: UUID | None,
) -> tuple[str | None, str | None, datetime | None, UUID | None]:
    if quality_state is None:
        return None, None, None, None

    now = datetime.now(UTC)
    reviewer_id = quality_reviewer_id

    if quality_state == DocumentQualityState.draft.value:
        return "draft", "current", None, None
    if quality_state == DocumentQualityState.verified.value:
        return "verified", "trusted", now, actor_user_id
    if quality_state == DocumentQualityState.reviewed.value:
        return "current", "current", now, reviewer_id or actor_user_id
    if quality_state == DocumentQualityState.unreviewed.value:
        return "current", "needs_review", None, None
    if quality_state == DocumentQualityState.stale.value:
        return "stale", "stale", None, None
    if quality_state == DocumentQualityState.expired.value:
        return "expired", "expired", None, None
    if quality_state == DocumentQualityState.deprecated.value:
        return "deprecated", "archived", None, None
    if quality_state == DocumentQualityState.archived.value:
        return "deprecated", "archived", None, None
    return None, None, None, None


def _document_deletion_item(doc: Document) -> AdminDocumentDeletionItem:
    return AdminDocumentDeletionItem(
        document_id=str(doc.id),
        filename=doc.filename,
        file_type=doc.file_type,
        status=DocumentStatus(doc.status),
        organization_id=str(doc.organization_id),
        deletion_requested_at=doc.deletion_requested_at,
        deletion_hold_reason=doc.deletion_hold_reason,
        error_message=doc.error_message,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("/deletion", response_model=AdminDocumentDeletionListResponse)
async def list_document_deletion_status(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    include_failed: bool = Query(
        default=False, description="Include documents that failed deletion"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AdminDocumentDeletionListResponse:
    organization_id = _organization_id_from_principal(principal)
    statuses = list(_DELETION_STATUSES)
    if include_failed:
        statuses.append(DocumentStatus.failed.value)

    documents, total = await document_repository.list_documents_for_deletion_admin(
        db_session,
        organization_id=organization_id,
        statuses=statuses,
        limit=limit,
        offset=offset,
    )
    return AdminDocumentDeletionListResponse(
        items=[_document_deletion_item(d) for d in documents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/deletion/{document_id}/retry",
    response_model=RetryDeleteDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_document_deletion(
    request: Request,
    document_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RetryDeleteDocumentResponse:
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    try:
        doc_uuid = UUID(document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid document_id format",
        ) from exc

    document = await document_repository.get_document_by_id(db_session, document_id=doc_uuid)
    if document is None or document.organization_id != actor_organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return await retry_delete_document_workflow(
        request_id=request_id,
        actor_user_id=actor_user_id,
        actor_organization_id=actor_organization_id,
        document=document,
        db_session=db_session,
        document_repository=document_repository,
        audit_log_service=audit_log_service,
        delete_document_task=delete_document_task,
    )


@router.patch(
    "/{document_id}/language",
    response_model=AdminLanguageOverrideResponse,
)
async def override_document_language(
    request: Request,
    document_id: str,
    payload: AdminLanguageOverrideRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminLanguageOverrideResponse:
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    try:
        doc_uuid = UUID(document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid document_id format",
        ) from exc

    document = await document_repository.get_document_by_id(db_session, document_id=doc_uuid)
    if document is None or document.organization_id != actor_organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    updated = await document_repository.update_document_language(
        db_session,
        document_id=doc_uuid,
        language=payload.language,
        language_confidence=None,
        language_source="admin_override",
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.language.override",
        resource_type="document",
        resource_id=doc_uuid,
        request_id=request_id,
        metadata={
            "language": payload.language,
            "language_source": "admin_override",
        },
    )
    await db_session.commit()

    return AdminLanguageOverrideResponse(
        document_id=str(updated.id),
        language=updated.language,
        language_source=updated.language_source,
        language_confidence=updated.language_confidence,
        updated_at=updated.updated_at,
    )


@router.patch(
    "/{document_id}/ocr-config",
    response_model=AdminOcrConfigResponse,
)
async def configure_document_ocr(
    request: Request,
    document_id: str,
    payload: AdminOcrConfigRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminOcrConfigResponse:
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    try:
        doc_uuid = UUID(document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid document_id format",
        ) from exc

    document = await document_repository.get_document_by_id(db_session, document_id=doc_uuid)
    if document is None or document.organization_id != actor_organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if payload.ocr_languages is not None:
        from app.domains.documents.services.ocr_language_config import iso_list_to_tesseract_string

        tesseract_str = (
            iso_list_to_tesseract_string(payload.ocr_languages) if payload.ocr_languages else None
        )
    else:
        tesseract_str = None

    updated = await document_repository.update_document_ocr_config(
        db_session,
        document_id=doc_uuid,
        ocr_languages_override=tesseract_str,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.ocr_config.updated",
        resource_type="document",
        resource_id=doc_uuid,
        request_id=request_id,
        metadata={
            "ocr_languages": payload.ocr_languages,
            "ocr_languages_override": tesseract_str,
        },
    )
    await db_session.commit()

    return AdminOcrConfigResponse(
        document_id=str(updated.id),
        ocr_languages_override=updated.ocr_languages_override,
        ocr_quality_snapshot=updated.ocr_quality_snapshot,
        updated_at=updated.updated_at,
    )


@router.patch(
    "/{document_id}/trust-status",
    response_model=AdminTrustStatusResponse,
)
async def update_document_trust_status(
    request: Request,
    document_id: str,
    payload: AdminTrustStatusRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminTrustStatusResponse:
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    try:
        doc_uuid = UUID(document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid document_id format",
        ) from exc

    document = await document_repository.get_document_by_id(db_session, document_id=doc_uuid)
    if document is None or document.organization_id != actor_organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    updated = await _update_document_trust_status_for_payload(
        db_session=db_session,
        actor_user_id=actor_user_id,
        actor_organization_id=actor_organization_id,
        request_id=request_id,
        document_id=doc_uuid,
        payload=payload,
    )
    await db_session.commit()

    return AdminTrustStatusResponse(
        document_id=str(updated.id),
        trust_status=updated.trust_status,
        quality_state=updated.quality_state,
        quality_notes=updated.quality_notes,
        quality_owner_id=str(updated.review_owner_id) if updated.review_owner_id else None,
        quality_reviewer_id=str(updated.trusted_by_id) if updated.trusted_by_id else None,
        review_status=updated.review_status,
        review_owner_id=str(updated.review_owner_id) if updated.review_owner_id else None,
        review_due_date=updated.review_due_date,
        expiry_date=updated.expiry_date,
        trust_level=updated.trust_level,
        version_label=updated.version_label,
        review_date=updated.review_date,
        effective_date=updated.effective_date,
        stale_after_days=updated.stale_after_days,
        superseded_by_document_id=str(updated.superseded_by_document_id)
        if updated.superseded_by_document_id
        else None,
        trusted_at=updated.trusted_at,
        updated_at=updated.updated_at,
    )


@router.post(
    "/bulk/trust-status",
    response_model=BulkAdminTrustStatusResponse,
)
async def bulk_update_document_trust_status(
    request: Request,
    payload: BulkAdminTrustStatusRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BulkAdminTrustStatusResponse:
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    updated = 0
    skipped = 0
    errors: list[str] = []
    results: list[BulkAdminTrustStatusResult] = []

    for document_id_text in payload.document_ids:
        try:
            document_uuid = UUID(document_id_text)
        except ValueError:
            skipped += 1
            error = f"Invalid document_id format: {document_id_text}"
            errors.append(error)
            results.append(
                BulkAdminTrustStatusResult(
                    document_id=document_id_text,
                    status="error",
                    error=error,
                )
            )
            continue

        try:
            await _update_document_trust_status_for_payload(
                db_session=db_session,
                actor_user_id=actor_user_id,
                actor_organization_id=actor_organization_id,
                request_id=request_id,
                document_id=document_uuid,
                payload=payload,
            )
            updated += 1
            results.append(
                BulkAdminTrustStatusResult(document_id=document_id_text, status="updated")
            )
        except HTTPException as exc:
            skipped += 1
            error = str(exc.detail)
            errors.append(f"[{document_id_text}] {error}")
            results.append(
                BulkAdminTrustStatusResult(
                    document_id=document_id_text,
                    status="skipped",
                    error=error,
                )
            )

    await db_session.commit()
    return BulkAdminTrustStatusResponse(
        updated=updated,
        skipped=skipped,
        errors=errors,
        results=results,
    )


# Low-OCR-quality statuses that are eligible for retry.
_OCR_RETRY_ELIGIBLE_STATUSES: frozenset[str] = frozenset(
    {OcrQualityStatus.low, OcrQualityStatus.failed}
)


@router.post(
    "/{document_id}/ocr-retry",
    response_model=AdminOcrRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_ocr_for_document(
    request: Request,
    document_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.admin))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AdminOcrRetryResponse:
    """Schedule a reindex for a document with low or failed OCR quality (F299).

    Only allowed for documents whose ocr_quality_status is 'low' or 'failed'.
    Admins should set ocr_languages_override via PATCH /{id}/ocr-config first
    if the language setting needs changing.
    """
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    try:
        doc_uuid = UUID(document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid document_id format",
        ) from exc

    document = await document_repository.get_document_by_id(db_session, document_id=doc_uuid)
    if document is None or document.organization_id != actor_organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document.ocr_quality_status not in _OCR_RETRY_ELIGIBLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"OCR retry is only allowed for documents with ocr_quality_status "
                f"'low' or 'failed'. Current status: '{document.ocr_quality_status}'."
            ),
        )

    reindex_document_task.delay(
        document_id=str(doc_uuid),
        organization_id=str(actor_organization_id),
        user_id=str(actor_user_id),
        request_id=request_id,
    )

    await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.ocr_retry.requested",
        resource_type="document",
        resource_id=doc_uuid,
        request_id=request_id,
        metadata={
            "ocr_quality_status": document.ocr_quality_status,
            "ocr_avg_confidence": document.ocr_avg_confidence,
        },
    )
    await db_session.commit()

    return AdminOcrRetryResponse(
        document_id=str(doc_uuid),
        ocr_quality_status=document.ocr_quality_status,
        ocr_avg_confidence=document.ocr_avg_confidence,
        queue_status="queued",
    )
