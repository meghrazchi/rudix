from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log_document_event
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.schemas.documents import (
    DeleteDocumentResponse,
    ReindexDocumentResponse,
    UploadDocumentResponse,
)
from app.domains.documents.services.upload_validation import validate_upload
from app.models.document import Document
from app.models.enums import DocumentStatus


def _object_key(
    *,
    organization_id: UUID,
    user_id: UUID,
    document_id: UUID,
    extension: str,
) -> str:
    return f"uploads/{organization_id}/{user_id}/{document_id}.{extension}"


def _is_queue_operational_error(exc: Exception) -> bool:
    # Avoid tight coupling to broker-specific exception classes in API layer.
    return exc.__class__.__name__ == "OperationalError"


async def _safe_commit_audit_only(db_session: AsyncSession, *, wrote_audit: bool) -> None:
    if not wrote_audit:
        return
    try:
        await db_session.commit()
    except Exception:
        await db_session.rollback()


async def upload_document_workflow(
    *,
    request_id: str | None,
    file: UploadFile,
    organization_id: UUID,
    user_id: UUID,
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    audit_log_service: AuditLogService,
    process_document_task: Any,
    minio_client: Any,
) -> UploadDocumentResponse:
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
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=message
            ) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc

    document_id = uuid4()
    object_key = _object_key(
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
        extension=validated.extension,
    )

    if minio_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is unavailable",
        )

    try:
        minio_client.put_object(
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
        delete_method = getattr(minio_client, "delete_object", None)
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
        task_result = process_document_task.delay(
            str(document.id),
            request_id=request_id,
            organization_id=str(organization_id),
            user_id=str(user_id),
        )
    except Exception as exc:
        if not settings.is_production and _is_queue_operational_error(exc):
            wrote_audit = await audit_log_service.record(
                db_session,
                organization_id=organization_id,
                user_id=user_id,
                action="document.upload.enqueue_deferred",
                resource_type="document",
                resource_id=document.id,
                request_id=request_id,
                metadata={
                    "status_code": status.HTTP_201_CREATED,
                    "error_type": exc.__class__.__name__,
                },
            )
            await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
            log_document_event(
                event="document.processing.enqueue_deferred",
                document_id=str(document.id),
                organization_id=str(organization_id),
                user_id=str(user_id),
                request_id=request_id,
                status_code=status.HTTP_201_CREATED,
                error=exc.__class__.__name__,
            )
            return UploadDocumentResponse(
                document_id=str(document.id),
                filename=document.filename,
                status=DocumentStatus.uploaded.value,
                queue_status="deferred",
                checksum=validated.checksum_sha256,
                message="Document uploaded; processing queue is temporarily unavailable.",
            )

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


async def delete_document_workflow(
    *,
    request_id: str | None,
    actor_user_id: UUID,
    actor_organization_id: UUID,
    document: Document,
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    audit_log_service: AuditLogService,
    delete_document_task: Any,
) -> DeleteDocumentResponse:
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
            organization_id=str(actor_organization_id),
            user_id=str(actor_user_id),
            request_id=request_id,
            status_code=status.HTTP_202_ACCEPTED,
        )
        return DeleteDocumentResponse(
            document_id=str(document.id), status=DocumentStatus.deleted.value
        )

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
            organization_id=str(actor_organization_id),
            user_id=str(actor_user_id),
            request_id=request_id,
            status_code=status.HTTP_202_ACCEPTED,
        )
        return DeleteDocumentResponse(
            document_id=str(document.id), status=DocumentStatus.deleting.value
        )

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
            organization_id=str(actor_organization_id),
            user_id=str(actor_user_id),
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
        organization_id=str(actor_organization_id),
        user_id=str(actor_user_id),
        request_id=request_id,
        task_id=str(task_result.id),
        status_code=status.HTTP_202_ACCEPTED,
    )
    return DeleteDocumentResponse(
        document_id=str(document.id),
        status=DocumentStatus.deleting.value,
    )


async def reindex_document_workflow(
    *,
    request_id: str | None,
    actor_user_id: UUID,
    actor_organization_id: UUID,
    document: Document,
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    audit_log_service: AuditLogService,
    reindex_document_task: Any,
) -> ReindexDocumentResponse:
    if document.status == DocumentStatus.deleted.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Deleted documents cannot be re-indexed"
        )
    if document.status == DocumentStatus.deleting.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Document is currently being deleted"
        )
    if document.status == DocumentStatus.processing.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Document is already being processed"
        )

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
            organization_id=str(actor_organization_id),
            user_id=str(actor_user_id),
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
        organization_id=str(actor_organization_id),
        user_id=str(actor_user_id),
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
