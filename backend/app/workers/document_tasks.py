from __future__ import annotations

from typing import Any

from app.core.logging import log_document_event
from app.models.enums import DocumentStatus
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app
from app.workers.status_tracking import get_document_status, set_document_status


class DocumentTask(RudixTask):
    abstract = True

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        document_id = kwargs.get("document_id")
        if document_id is None and args:
            document_id = args[0]
        if not isinstance(document_id, str):
            return
        try:
            set_document_status(
                document_id,
                status=DocumentStatus.failed,
                error_message=str(exc),
            )
            log_document_event(
                event="document.processing.failed",
                document_id=document_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=DocumentStatus.failed.value,
                error=str(exc),
            )
        except Exception:
            return


@celery_app.task(name="documents.process", bind=True, base=DocumentTask)
def process_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    force: bool = False,
) -> dict[str, str]:
    """Scaffold task for extract/chunk/embed/index lifecycle orchestration."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")

    if not force and status in {DocumentStatus.indexed.value, DocumentStatus.deleted.value}:
        log_document_event(
            event="document.processing.skipped",
            document_id=document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code=status,
        )
        return {"document_id": document_id, "status": "skipped"}

    try:
        processing_updated = set_document_status(document_id, status=DocumentStatus.processing)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if not processing_updated:
        raise TransientTaskError(f"Unable to move document to processing state: {document_id}")

    log_document_event(
        event="document.processing.started",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.processing.value,
    )

    indexed_updated = set_document_status(document_id, status=DocumentStatus.indexed)
    if not indexed_updated:
        raise TransientTaskError(f"Unable to move document to indexed state: {document_id}")

    log_document_event(
        event="document.processing.completed",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.indexed.value,
    )
    return {"document_id": document_id, "status": DocumentStatus.indexed.value}


@celery_app.task(name="documents.delete", bind=True, base=DocumentTask)
def delete_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str]:
    """Scaffold task for idempotent document deletion orchestration."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")

    if status == DocumentStatus.deleted.value:
        log_document_event(
            event="document.deletion.skipped",
            document_id=document_id,
            request_id=request_id,
            organization_id=organization_id,
            user_id=user_id,
            status_code=status,
        )
        return {"document_id": document_id, "status": "skipped"}

    deleting_updated = set_document_status(document_id, status=DocumentStatus.deleting)
    if not deleting_updated:
        raise TransientTaskError(f"Unable to move document to deleting state: {document_id}")
    deleted_updated = set_document_status(document_id, status=DocumentStatus.deleted)
    if not deleted_updated:
        raise TransientTaskError(f"Unable to move document to deleted state: {document_id}")

    log_document_event(
        event="document.deletion.completed",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.deleted.value,
    )
    return {"document_id": document_id, "status": DocumentStatus.deleted.value}


@celery_app.task(name="documents.reindex", bind=True, base=DocumentTask)
def reindex_document(
    self: DocumentTask,
    document_id: str,
    *,
    request_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, str]:
    """Scaffold task for idempotent document re-index orchestration."""
    try:
        status = get_document_status(document_id)
    except ValueError as exc:
        raise PermanentTaskError(f"Invalid document_id: {document_id}") from exc
    if status is None:
        raise PermanentTaskError(f"Document not found: {document_id}")
    if status == DocumentStatus.deleted.value:
        raise PermanentTaskError(f"Cannot reindex deleted document: {document_id}")

    processing_updated = set_document_status(document_id, status=DocumentStatus.processing)
    if not processing_updated:
        raise TransientTaskError(f"Unable to move document to processing state: {document_id}")
    indexed_updated = set_document_status(document_id, status=DocumentStatus.indexed)
    if not indexed_updated:
        raise TransientTaskError(f"Unable to move document to indexed state: {document_id}")

    log_document_event(
        event="document.reindex.completed",
        document_id=document_id,
        request_id=request_id,
        organization_id=organization_id,
        user_id=user_id,
        status_code=DocumentStatus.indexed.value,
    )
    return {"document_id": document_id, "status": DocumentStatus.indexed.value}
