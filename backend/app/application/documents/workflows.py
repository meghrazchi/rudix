import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import log_document_event
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.schemas.documents import (
    BulkDeleteDocumentResult,
    BulkDeleteDocumentsResponse,
    DeleteDocumentResponse,
    ReindexDocumentResponse,
    RetryDeleteDocumentResponse,
    UploadDocumentMetadata,
    UploadDocumentResponse,
)
from app.domains.documents.services.duplicate_detection import check_for_duplicate
from app.domains.documents.services.malware_scan import MalwareScanResult, MalwareScanService
from app.domains.documents.services.upload_validation import validate_upload
from app.models.collection import Collection, CollectionDocument
from app.models.document import Document
from app.models.enums import DocumentStatus

_LEGAL_HOLD_RETENTION_CLASSES = frozenset({"legal_hold"})

_SAFE_SIGNATURE_PATTERN = re.compile(r"^[A-Za-z0-9._:+\- ]+$")


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


def _safe_signature_name(signature: str | None) -> str | None:
    if signature is None:
        return None
    cleaned = " ".join(signature.strip().split())
    if not cleaned:
        return None
    cleaned = cleaned[:120]
    if not _SAFE_SIGNATURE_PATTERN.fullmatch(cleaned):
        return None
    return cleaned


def _should_bypass_scan_error(scan_result: MalwareScanResult) -> bool:
    if not settings.malware_scan_required:
        return True
    if settings.is_production:
        return False
    if not settings.malware_scan_bypass_on_unavailable:
        return False
    return scan_result.error_type in {"unavailable", "timeout"}


async def _assign_collection(
    db_session: AsyncSession,
    *,
    document_id: UUID,
    collection_id: UUID,
    organization_id: UUID,
) -> bool:
    result = await db_session.execute(
        select(Collection).where(
            Collection.id == collection_id,
            Collection.organization_id == organization_id,
            Collection.is_archived.is_(False),
        )
    )
    if result.scalar_one_or_none() is None:
        return False

    membership = CollectionDocument(
        collection_id=collection_id,
        document_id=document_id,
    )
    db_session.add(membership)
    try:
        await db_session.flush()
    except IntegrityError:
        await db_session.rollback()
    return True


async def upload_document_workflow(
    *,
    request_id: str | None,
    file: UploadFile,
    organization_id: UUID,
    user_id: UUID,
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    audit_log_service: AuditLogService,
    malware_scan_service: MalwareScanService,
    process_document_task: Any,
    minio_client: Any,
    upload_metadata: UploadDocumentMetadata | None = None,
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

    scan_result = await malware_scan_service.scan_bytes(content=content)
    safe_signature = _safe_signature_name(scan_result.signature)
    scan_metadata = {
        "filename": validated.normalized_filename,
        "file_type": validated.extension,
        "file_size_bytes": validated.file_size_bytes,
        "checksum": validated.checksum_sha256,
        "scanner": scan_result.scanner,
        "scanner_result": scan_result.status,
        "signature": safe_signature,
        "duration_ms": scan_result.duration_ms,
        "error_type": scan_result.error_type,
    }

    if scan_result.status == "infected":
        wrote_audit = await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="document.upload.rejected_malware",
            resource_type="document",
            resource_id=document_id,
            request_id=request_id,
            metadata=scan_metadata,
        )
        await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
        log_document_event(
            event="document.upload.scan.rejected",
            document_id=str(document_id),
            organization_id=str(organization_id),
            user_id=str(user_id),
            request_id=request_id,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            scanner=scan_result.scanner,
            scanner_result=scan_result.status,
            signature=safe_signature,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="File failed security scan",
        )

    if scan_result.status == "error":
        bypass_scan_error = _should_bypass_scan_error(scan_result)
        action = (
            "document.upload.scan_unavailable_bypassed"
            if bypass_scan_error
            else "document.upload.scan_unavailable_rejected"
        )
        wrote_audit = await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type="document",
            resource_id=document_id,
            request_id=request_id,
            metadata=scan_metadata,
        )
        await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
        log_document_event(
            event=(
                "document.upload.scan.unavailable_bypassed"
                if bypass_scan_error
                else "document.upload.scan.unavailable_rejected"
            ),
            document_id=str(document_id),
            organization_id=str(organization_id),
            user_id=str(user_id),
            request_id=request_id,
            status_code=(
                status.HTTP_201_CREATED
                if bypass_scan_error
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            scanner=scan_result.scanner,
            scanner_result=scan_result.status,
            error_type=scan_result.error_type,
        )
        if not bypass_scan_error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="File security scan unavailable",
            )

    # Duplicate detection — runs after scan so we don't record duplicates of infected files.
    duplicate_result = await check_for_duplicate(
        db_session,
        checksum=validated.checksum_sha256,
        organization_id=organization_id,
        enabled=settings.duplicate_detection_enabled,
        action=settings.duplicate_detection_action,  # type: ignore[arg-type]
    )
    if duplicate_result.is_duplicate and duplicate_result.action == "reject":
        wrote_audit = await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="document.upload.rejected_duplicate",
            resource_type="document",
            resource_id=document_id,
            request_id=request_id,
            metadata={
                "filename": validated.normalized_filename,
                "checksum": validated.checksum_sha256,
                "existing_document_id": str(duplicate_result.existing_document_id),
            },
        )
        await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
        log_document_event(
            event="document.upload.rejected_duplicate",
            document_id=str(document_id),
            organization_id=str(organization_id),
            user_id=str(user_id),
            request_id=request_id,
            status_code=status.HTTP_409_CONFLICT,
            existing_document_id=str(duplicate_result.existing_document_id),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A document with the same content already exists in this organization",
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

    meta = upload_metadata or UploadDocumentMetadata()
    tags_str = ",".join(meta.tags) if meta.tags else None

    security_scan_result = {
        "scanner": scan_result.scanner,
        "scanner_result": scan_result.status,
        "duration_ms": scan_result.duration_ms,
        "duplicate_detected": duplicate_result.is_duplicate,
        "duplicate_action": duplicate_result.action if duplicate_result.is_duplicate else None,
    }

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
            source=meta.source,
            language=meta.language,
            language_source="upload_provided" if meta.language else None,
            retention_class=meta.retention_class,
            notes=meta.notes,
            tags=tags_str,
            duplicate_of_document_id=duplicate_result.existing_document_id,
            security_scan_result=security_scan_result,
        )

        collection_assigned = False
        if meta.collection_id:
            try:
                collection_uuid = UUID(meta.collection_id)
                collection_assigned = await _assign_collection(
                    db_session,
                    document_id=document.id,
                    collection_id=collection_uuid,
                    organization_id=organization_id,
                )
            except (ValueError, Exception):
                pass

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
                "collection_assigned": collection_assigned,
                "duplicate_detected": duplicate_result.is_duplicate,
                "duplicate_action": duplicate_result.action if duplicate_result.is_duplicate else None,
                "existing_document_id": str(duplicate_result.existing_document_id)
                if duplicate_result.existing_document_id
                else None,
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
                collection_assigned=collection_assigned,
                duplicate_detected=duplicate_result.is_duplicate,
                duplicate_document_id=str(duplicate_result.existing_document_id)
                if duplicate_result.existing_document_id
                else None,
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

    duplicate_message = ""
    if duplicate_result.is_duplicate and duplicate_result.action == "warn":
        duplicate_message = " A document with the same content already exists in this organization."

    return UploadDocumentResponse(
        document_id=str(document.id),
        filename=document.filename,
        status=DocumentStatus.uploaded.value,
        queue_status="queued",
        checksum=validated.checksum_sha256,
        message=f"Document uploaded and queued for processing.{duplicate_message}",
        collection_assigned=collection_assigned,
        duplicate_detected=duplicate_result.is_duplicate,
        duplicate_document_id=str(duplicate_result.existing_document_id)
        if duplicate_result.existing_document_id
        else None,
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
    # Retention/legal hold check — must run before any status transition.
    if document.retention_class in _LEGAL_HOLD_RETENTION_CLASSES:
        hold_reason = (
            document.deletion_hold_reason
            or f"Document is under {document.retention_class} and cannot be deleted."
        )
        updated = await document_repository.update_document_status(
            db_session,
            document_id=document.id,
            status=DocumentStatus.retained_by_policy.value,
            error_message=hold_reason,
        )
        if updated is not None:
            await audit_log_service.record(
                db_session,
                organization_id=actor_organization_id,
                user_id=actor_user_id,
                action="document.delete.retained",
                resource_type="document",
                resource_id=document.id,
                request_id=request_id,
                metadata={
                    "retention_class": document.retention_class,
                    "hold_reason": hold_reason,
                },
            )
            await db_session.commit()
        log_document_event(
            event="document.deletion.retained_by_policy",
            document_id=str(document.id),
            organization_id=str(actor_organization_id),
            user_id=str(actor_user_id),
            request_id=request_id,
            retention_class=document.retention_class,
        )
        return DeleteDocumentResponse(
            document_id=str(document.id),
            status=DocumentStatus.retained_by_policy.value,
            hold_reason=hold_reason,
        )

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

    if document.status in {
        DocumentStatus.deleting.value,
        DocumentStatus.delete_requested.value,
    }:
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
            document_id=str(document.id), status=document.status
        )

    # Transition to delete_requested before attempting to enqueue.
    updated = await document_repository.update_document_status(
        db_session,
        document_id=document.id,
        status=DocumentStatus.delete_requested.value,
        error_message=None,
    )
    if updated is None:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    await document_repository.set_deletion_requested_at(
        db_session,
        document_id=document.id,
        deletion_requested_at=datetime.now(UTC),
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
            "next_status": DocumentStatus.delete_requested.value,
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
        status=DocumentStatus.delete_requested.value,
    )


async def bulk_delete_documents_workflow(
    *,
    request_id: str | None,
    actor_user_id: UUID,
    actor_organization_id: UUID,
    document_ids: list[str],
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    audit_log_service: AuditLogService,
    delete_document_task: Any,
) -> BulkDeleteDocumentsResponse:
    results: list[BulkDeleteDocumentResult] = []
    accepted = 0
    retained = 0
    errors = 0

    for doc_id in document_ids:
        try:
            doc_uuid = UUID(doc_id)
        except ValueError:
            results.append(
                BulkDeleteDocumentResult(
                    document_id=doc_id,
                    status="error",
                    error="Invalid document ID format",
                )
            )
            errors += 1
            continue

        doc = await document_repository.get_document_by_id(db_session, document_id=doc_uuid)
        if doc is None or doc.organization_id != actor_organization_id:
            results.append(
                BulkDeleteDocumentResult(document_id=doc_id, status="not_found")
            )
            errors += 1
            continue

        try:
            response = await delete_document_workflow(
                request_id=request_id,
                actor_user_id=actor_user_id,
                actor_organization_id=actor_organization_id,
                document=doc,
                db_session=db_session,
                document_repository=document_repository,
                audit_log_service=audit_log_service,
                delete_document_task=delete_document_task,
            )
            result_status = response.status
            if result_status == "retained_by_policy":
                retained += 1
            else:
                accepted += 1
            results.append(
                BulkDeleteDocumentResult(
                    document_id=doc_id,
                    status=result_status,
                    hold_reason=response.hold_reason,
                )
            )
        except HTTPException as exc:
            results.append(
                BulkDeleteDocumentResult(
                    document_id=doc_id,
                    status="error",
                    error=exc.detail,
                )
            )
            errors += 1

    return BulkDeleteDocumentsResponse(
        accepted=accepted,
        retained=retained,
        errors=errors,
        results=results,
    )


async def retry_delete_document_workflow(
    *,
    request_id: str | None,
    actor_user_id: UUID,
    actor_organization_id: UUID,
    document: Document,
    db_session: AsyncSession,
    document_repository: DocumentRepository,
    audit_log_service: AuditLogService,
    delete_document_task: Any,
) -> RetryDeleteDocumentResponse:
    retryable_statuses = {
        DocumentStatus.delete_requested.value,
        DocumentStatus.deleting.value,
        DocumentStatus.failed.value,
    }
    if document.status not in retryable_statuses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document status '{document.status}' is not retryable. "
            "Only delete_requested, deleting, or failed documents can be retried.",
        )

    # Move back to delete_requested before re-enqueuing.
    updated = await document_repository.update_document_status(
        db_session,
        document_id=document.id,
        status=DocumentStatus.delete_requested.value,
        error_message=None,
    )
    if updated is None:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if document.deletion_requested_at is None:
        await document_repository.set_deletion_requested_at(
            db_session,
            document_id=document.id,
            deletion_requested_at=datetime.now(UTC),
        )
    await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.delete.retry_requested",
        resource_type="document",
        resource_id=document.id,
        request_id=request_id,
        metadata={"previous_status": document.status},
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
                "error_type": exc.__class__.__name__,
                "retry": True,
            },
        )
        await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document marked for re-deletion but could not be queued",
        ) from exc

    wrote_audit = await audit_log_service.record(
        db_session,
        organization_id=actor_organization_id,
        user_id=actor_user_id,
        action="document.delete.queued",
        resource_type="document",
        resource_id=document.id,
        request_id=request_id,
        metadata={"task_id": str(task_result.id), "retry": True},
    )
    await _safe_commit_audit_only(db_session, wrote_audit=wrote_audit)

    log_document_event(
        event="document.deletion.retry_queued",
        document_id=str(document.id),
        organization_id=str(actor_organization_id),
        user_id=str(actor_user_id),
        request_id=request_id,
        task_id=str(task_result.id),
    )
    return RetryDeleteDocumentResponse(
        document_id=str(document.id),
        status=DocumentStatus.delete_requested.value,
        queue_status="queued",
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
    chunking_profile_config: dict | None = None,
) -> ReindexDocumentResponse:
    if document.status == DocumentStatus.deleted.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Deleted documents cannot be re-indexed"
        )
    if document.status == DocumentStatus.deleting.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Document is currently being deleted"
        )
    if document.status == DocumentStatus.quarantined.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Quarantined documents cannot be re-indexed without admin review",
        )
    if document.status == DocumentStatus.blocked.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Blocked documents cannot be re-indexed",
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
            "chunking_strategy": chunking_profile_config.get("strategy")
            if chunking_profile_config
            else None,
        },
    )
    await db_session.commit()

    try:
        task_kwargs: dict[str, Any] = {
            "request_id": request_id,
            "organization_id": str(actor_organization_id),
            "user_id": str(actor_user_id),
        }
        if chunking_profile_config is not None:
            task_kwargs["chunking_profile_config"] = chunking_profile_config
        task_result = reindex_document_task.delay(str(document.id), **task_kwargs)
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
            "chunking_strategy": chunking_profile_config.get("strategy")
            if chunking_profile_config
            else None,
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
