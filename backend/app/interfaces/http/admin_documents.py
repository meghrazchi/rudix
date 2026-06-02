from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.documents.workflows import retry_delete_document_workflow
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.schemas.documents import (
    AdminDocumentDeletionItem,
    AdminDocumentDeletionListResponse,
    RetryDeleteDocumentResponse,
)
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.workers.document_tasks import delete_document as delete_document_task

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
    include_failed: bool = Query(default=False, description="Include documents that failed deletion"),
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
