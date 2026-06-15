from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, field_validator
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
from app.models.enums import DocumentStatus, DocumentTrustStatus, OrganizationRole
from app.models.enums import OcrQualityStatus
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.workers.document_tasks import delete_document as delete_document_task
from app.workers.document_tasks import reindex_document as reindex_document_task

_ALLOWED_TRUST_STATUSES = frozenset(s.value for s in DocumentTrustStatus)


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


class AdminTrustStatusResponse(BaseModel):
    document_id: str
    trust_status: str
    version_label: str | None
    review_date: date | None
    effective_date: date | None
    stale_after_days: int | None
    superseded_by_document_id: str | None
    trusted_at: datetime | None
    updated_at: datetime


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


def _request_id_from_request(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")


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

    now = datetime.now(UTC)
    trusted_at = now if payload.trust_status == DocumentTrustStatus.verified.value else None
    trusted_by_id = actor_user_id if payload.trust_status == DocumentTrustStatus.verified.value else None

    updated = await document_repository.update_document_trust_status(
        db_session,
        document_id=doc_uuid,
        trust_status=payload.trust_status,
        version_label=payload.version_label,
        review_date=payload.review_date,
        effective_date=payload.effective_date,
        stale_after_days=payload.stale_after_days,
        superseded_by_document_id=superseded_by_uuid,
        trusted_at=trusted_at,
        trusted_by_id=trusted_by_id,
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
        resource_id=doc_uuid,
        request_id=request_id,
        metadata={
            "trust_status": payload.trust_status,
            "version_label": payload.version_label,
            "review_date": payload.review_date.isoformat() if payload.review_date else None,
            "effective_date": payload.effective_date.isoformat() if payload.effective_date else None,
            "stale_after_days": payload.stale_after_days,
            "superseded_by_document_id": payload.superseded_by_document_id,
        },
    )
    await db_session.commit()

    return AdminTrustStatusResponse(
        document_id=str(updated.id),
        trust_status=updated.trust_status,
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
