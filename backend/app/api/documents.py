from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal, require_document_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.clients import minio_client as minio_module
from app.core.config import settings
from app.core.document_errors import decode_document_error
from app.core.logging import log_document_event
from app.db.session import get_db_session
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.repositories.documents import DocumentRepository
from app.schemas.documents import (
    CreateUploadUrlRequest,
    CreateUploadUrlResponse,
    DeleteDocumentResponse,
    DocumentChunkPreviewResponse,
    DocumentChunksResponse,
    DocumentDetailResponse,
    DocumentListItemResponse,
    DocumentListResponse,
    DocumentSortBy,
    DocumentStatusResponse,
    ReindexDocumentResponse,
    SortOrder,
    UploadDocumentResponse,
)
from app.services.audit_service import AuditLogService
from app.services.upload_validation import validate_upload
from app.workers.document_tasks import delete_document as delete_document_task
from app.workers.document_tasks import process_document
from app.workers.document_tasks import reindex_document as reindex_document_task

router = APIRouter(prefix="/documents", tags=["documents"])
document_repository = DocumentRepository()
audit_log_service = AuditLogService()


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


def _object_key(
    *,
    organization_id: UUID,
    user_id: UUID,
    document_id: UUID,
    extension: str,
) -> str:
    return f"uploads/{organization_id}/{user_id}/{document_id}.{extension}"


def _safe_error_payload(document: Document) -> tuple[str | None, object | None]:
    error_message, error_details = decode_document_error(document.error_message)
    if document.error_message is None:
        return None, None
    if error_details is not None:
        return error_message, error_details
    # Legacy/plain errors are not exposed verbatim.
    return "Processing failed", None


def _chunk_preview_text(text: str, *, max_length: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


async def _safe_commit_audit_only(db_session: AsyncSession, *, wrote_audit: bool) -> None:
    if not wrote_audit:
        return
    try:
        await db_session.commit()
    except Exception:
        await db_session.rollback()


@router.post("/upload", response_model=UploadDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.upload))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> UploadDocumentResponse:
    request_id = _request_id_from_request(request)
    max_size_bytes = settings.max_upload_size_mb * 1024 * 1024
    try:
        content = await file.read(max_size_bytes + 1)
    finally:
        await file.close()

    try:
        validated = validate_upload(
            filename=file.filename or "",
            content_type=file.content_type,
            content=content,
            max_size_bytes=max_size_bytes,
        )
    except OverflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.max_upload_size_mb} MB",
        ) from exc
    except ValueError as exc:
        message = str(exc)
        if message in {"unsupported file extension", "unsupported mime type"}:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc

    user_id, organization_id = _principal_user_and_org(principal)
    document_id = uuid4()
    object_key = _object_key(
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
        extension=validated.extension,
    )

    minio = minio_module.minio_client
    if minio is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        )

    try:
        minio.put_object(
            Bucket=settings.minio_bucket,
            Key=object_key,
            Body=content,
            ContentType=validated.content_type,
            ContentLength=validated.file_size_bytes,
        )
    except Exception as exc:
        log_document_event(
            event="document.upload.failed",
            organization_id=str(organization_id),
            user_id=str(user_id),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload storage operation failed",
        ) from exc

    try:
        document = await document_repository.create_document(
            db_session,
            document_id=document_id,
            organization_id=organization_id,
            uploaded_by_user_id=user_id,
            filename=validated.normalized_filename,
            file_type=validated.extension,
            storage_bucket=settings.minio_bucket,
            storage_object_key=object_key,
            checksum=validated.checksum_sha256,
            status=DocumentStatus.uploaded.value,
        )
        await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="document.upload.accepted",
            resource_type="document",
            resource_id=document.id,
            request_id=request_id,
            metadata={
                "filename": validated.normalized_filename,
                "file_type": validated.extension,
                "file_size_bytes": validated.file_size_bytes,
                "status": DocumentStatus.uploaded.value,
            },
        )
        await db_session.commit()
        await db_session.refresh(document)
    except Exception as exc:
        await db_session.rollback()
        delete_method = getattr(minio, "delete_object", None)
        if callable(delete_method):
            try:
                delete_method(Bucket=settings.minio_bucket, Key=object_key)
            except Exception:
                pass
        log_document_event(
            event="document.upload.metadata_failed",
            organization_id=str(organization_id),
            user_id=str(user_id),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist document metadata",
        ) from exc

    log_document_event(
        event="document.upload.accepted",
        document_id=str(document.id),
        organization_id=str(organization_id),
        user_id=str(user_id),
        request_id=request_id,
        status_code=status.HTTP_201_CREATED,
        file_type=validated.extension,
        file_size_bytes=validated.file_size_bytes,
    )

    try:
        task_result = process_document.delay(
            str(document.id),
            request_id=request_id,
            organization_id=str(organization_id),
            user_id=str(user_id),
        )
    except Exception as exc:
        wrote_audit = await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="document.upload.enqueue_failed",
            resource_type="document",
            resource_id=document.id,
            request_id=request_id,
            metadata={
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "error_type": exc.__class__.__name__,
            },
        )
        await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
        log_document_event(
            event="document.processing.enqueue_failed",
            document_id=str(document.id),
            organization_id=str(organization_id),
            user_id=str(user_id),
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document uploaded but could not be queued for processing",
        ) from exc

    log_document_event(
        event="document.processing.queued",
        document_id=str(document.id),
        organization_id=str(organization_id),
        user_id=str(user_id),
        request_id=request_id,
        task_id=str(task_result.id),
        status_code=status.HTTP_201_CREATED,
    )

    return UploadDocumentResponse(
        document_id=str(document.id),
        filename=document.filename,
        status=DocumentStatus.uploaded.value,
        queue_status="queued",
        checksum=validated.checksum_sha256,
        message="Document uploaded and queued for processing.",
    )


@router.post("/upload-url", response_model=CreateUploadUrlResponse)
async def create_upload_url(
    payload: CreateUploadUrlRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    rate_limit: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.upload))],
) -> CreateUploadUrlResponse:
    del payload, rate_limit
    log_document_event(
        event="document.upload_url.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Upload URL generation is not implemented in scaffold.",
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    sort_by: DocumentSortBy = "created_at",
    sort_order: SortOrder = "desc",
) -> DocumentListResponse:
    _, organization_id = _principal_user_and_org(principal)

    documents = await document_repository.list_documents(
        db_session,
        organization_id=organization_id,
        status=status_filter.value if status_filter is not None else None,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = await document_repository.count_documents(
        db_session,
        organization_id=organization_id,
        status=status_filter.value if status_filter is not None else None,
    )

    items: list[DocumentListItemResponse] = []
    for document in documents:
        chunk_count = await document_repository.count_document_chunks(
            db_session,
            document_id=document.id,
            index_version=settings.document_index_version,
        )
        safe_error_message, safe_error_details = _safe_error_payload(document)
        items.append(
            DocumentListItemResponse(
                document_id=str(document.id),
                filename=document.filename,
                file_type=document.file_type,
                status=document.status,
                page_count=document.page_count,
                chunk_count=chunk_count,
                error_message=safe_error_message,
                error_details=safe_error_details,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
        )

    log_document_event(
        event="document.list.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
        status_filter=status_filter.value if status_filter is not None else None,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return DocumentListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        status=status_filter,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/{document_id}/chunks", response_model=DocumentChunksResponse)
async def get_document_chunks(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_access)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_full_text: bool = False,
) -> DocumentChunksResponse:
    del document_id
    chunks = await document_repository.list_document_chunks_paginated(
        db_session,
        document_id=document.id,
        index_version=settings.document_index_version,
        limit=limit,
        offset=offset,
    )
    total = await document_repository.count_document_chunks(
        db_session,
        document_id=document.id,
        index_version=settings.document_index_version,
    )

    items = [
        DocumentChunkPreviewResponse(
            chunk_id=str(chunk.id),
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            token_count=chunk.token_count,
            embedding_model=chunk.embedding_model,
            index_version=chunk.index_version,
            text_preview=_chunk_preview_text(chunk.text),
            text=chunk.text if include_full_text else None,
            created_at=chunk.created_at,
        )
        for chunk in chunks
    ]

    log_document_event(
        event="document.chunks.requested",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        limit=limit,
        offset=offset,
        total=total,
        returned=len(items),
        include_full_text=include_full_text,
    )
    return DocumentChunksResponse(
        document_id=str(document.id),
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        include_full_text=include_full_text,
    )


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_access)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentDetailResponse:
    del document_id
    safe_error_message, safe_error_details = _safe_error_payload(document)
    chunk_count = await document_repository.count_document_chunks(
        db_session,
        document_id=document.id,
        index_version=settings.document_index_version,
    )
    log_document_event(
        event="document.detail.requested",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        document_status=document.status,
    )
    return DocumentDetailResponse(
        document_id=str(document.id),
        filename=document.filename,
        file_type=document.file_type,
        status=document.status,
        page_count=document.page_count,
        chunk_count=chunk_count,
        checksum=document.checksum,
        error_message=safe_error_message,
        error_details=safe_error_details,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.delete("/{document_id}", response_model=DeleteDocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def delete_document_endpoint(
    request: Request,
    document_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.delete))],
    document: Annotated[Document, Depends(require_document_access)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DeleteDocumentResponse:
    del document_id
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    if document.status == DocumentStatus.deleted.value:
        wrote_audit = await audit_log_service.record(
            db_session,
            organization_id=actor_organization_id,
            user_id=actor_user_id,
            action="document.delete.skipped",
            resource_type="document",
            resource_id=document.id,
            request_id=request_id,
            metadata={"reason": "already_deleted", "status": document.status},
        )
        await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
        log_document_event(
            event="document.deletion.already_deleted",
            document_id=str(document.id),
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            request_id=request_id,
            status_code=status.HTTP_202_ACCEPTED,
        )
        return DeleteDocumentResponse(document_id=str(document.id), status=DocumentStatus.deleted.value)

    if document.status == DocumentStatus.deleting.value:
        wrote_audit = await audit_log_service.record(
            db_session,
            organization_id=actor_organization_id,
            user_id=actor_user_id,
            action="document.delete.skipped",
            resource_type="document",
            resource_id=document.id,
            request_id=request_id,
            metadata={"reason": "already_deleting", "status": document.status},
        )
        await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
        log_document_event(
            event="document.deletion.already_queued",
            document_id=str(document.id),
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            request_id=request_id,
            status_code=status.HTTP_202_ACCEPTED,
        )
        return DeleteDocumentResponse(document_id=str(document.id), status=DocumentStatus.deleting.value)

    updated = await document_repository.update_document_status(
        db_session,
        document_id=document.id,
        status=DocumentStatus.deleting.value,
        error_message=None,
    )
    if updated is None:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.delete.requested",
        resource_type="document",
        resource_id=document.id,
        request_id=request_id,
        metadata={
            "previous_status": document.status,
            "next_status": DocumentStatus.deleting.value,
        },
    )
    await db_session.commit()

    try:
        task_result = delete_document_task.delay(
            str(document.id),
            request_id=request_id,
            organization_id=str(actor_organization_id),
            user_id=str(actor_user_id),
        )
    except Exception as exc:
        wrote_audit = await audit_log_service.record(
            db_session,
            organization_id=actor_organization_id,
            user_id=actor_user_id,
            action="document.delete.enqueue_failed",
            resource_type="document",
            resource_id=document.id,
            request_id=request_id,
            metadata={
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "error_type": exc.__class__.__name__,
            },
        )
        await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
        log_document_event(
            event="document.deletion.enqueue_failed",
            document_id=str(document.id),
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document marked for deletion but could not be queued",
        ) from exc

    wrote_audit = await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.delete.queued",
        resource_type="document",
        resource_id=document.id,
        request_id=request_id,
        metadata={
            "task_id": str(task_result.id),
            "status_code": status.HTTP_202_ACCEPTED,
        },
    )
    await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)

    log_document_event(
        event="document.deletion.queued",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        request_id=request_id,
        task_id=str(task_result.id),
        status_code=status.HTTP_202_ACCEPTED,
    )
    return DeleteDocumentResponse(
        document_id=str(document.id),
        status=DocumentStatus.deleting.value,
    )


@router.post("/{document_id}/reindex", response_model=ReindexDocumentResponse, status_code=status.HTTP_202_ACCEPTED)
async def reindex_document_endpoint(
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
    document: Annotated[Document, Depends(require_document_access)],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReindexDocumentResponse:
    del document_id
    request_id = _request_id_from_request(request)
    actor_user_id, actor_organization_id = _principal_user_and_org(principal)

    if document.status == DocumentStatus.deleted.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deleted documents cannot be re-indexed")
    if document.status == DocumentStatus.deleting.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document is currently being deleted")
    if document.status == DocumentStatus.processing.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document is already being processed")

    previous_status = document.status
    previous_error_message = document.error_message
    updated = await document_repository.update_document_status(
        db_session,
        document_id=document.id,
        status=DocumentStatus.processing.value,
        error_message=None,
    )
    if updated is None:
        await db_session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.reindex.requested",
        resource_type="document",
        resource_id=document.id,
        request_id=request_id,
        metadata={
            "previous_status": previous_status,
            "next_status": DocumentStatus.processing.value,
        },
    )
    await db_session.commit()

    try:
        task_result = reindex_document_task.delay(
            str(document.id),
            request_id=request_id,
            organization_id=str(actor_organization_id),
            user_id=str(actor_user_id),
        )
    except Exception as exc:
        await audit_log_service.record(
            db_session,
            organization_id=actor_organization_id,
            user_id=actor_user_id,
            action="document.reindex.enqueue_failed",
            resource_type="document",
            resource_id=document.id,
            request_id=request_id,
            metadata={
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "error_type": exc.__class__.__name__,
                "restored_status": previous_status,
            },
        )
        log_document_event(
            event="document.reindex.enqueue_failed",
            document_id=str(document.id),
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            request_id=request_id,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
        )
        try:
            _ = await document_repository.update_document_status(
                db_session,
                document_id=document.id,
                status=previous_status,
                error_message=previous_error_message,
            )
            await db_session.commit()
        except Exception:
            await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document re-index request could not be queued",
        ) from exc

    wrote_audit = await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.reindex.queued",
        resource_type="document",
        resource_id=document.id,
        request_id=request_id,
        metadata={
            "task_id": str(task_result.id),
            "status_code": status.HTTP_202_ACCEPTED,
            "previous_status": previous_status,
        },
    )
    await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)

    log_document_event(
        event="document.reindex.queued",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        request_id=request_id,
        task_id=str(task_result.id),
        status_code=status.HTTP_202_ACCEPTED,
        previous_status=previous_status,
    )
    return ReindexDocumentResponse(
        document_id=str(document.id),
        status=DocumentStatus.processing.value,
        queue_status="queued",
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    document: Annotated[Document, Depends(require_document_access)],
) -> DocumentStatusResponse:
    del document_id
    safe_error_message, safe_error_details = _safe_error_payload(document)
    log_document_event(
        event="document.status.requested",
        document_id=str(document.id),
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        document_status=document.status,
    )
    return DocumentStatusResponse(
        document_id=str(document.id),
        status=document.status,
        error_message=safe_error_message,
        error_details=safe_error_details,
        updated_at=document.updated_at,
    )
