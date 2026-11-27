"""Celery base classes of the document tasks (moved from document_tasks, R06-01).

``on_terminal_failure`` behaviour is unchanged; status, audit, and log helpers are read
from the facade at call time so tests that rebind them on ``document_tasks`` still apply.
"""

from __future__ import annotations

from typing import Any

from app.core.document_errors import details_from_exception, encode_document_error
from app.domains.documents.repositories.processing_claims import (
    TERMINAL_FAILURE_PROTECTED_STATUSES,
)
from app.models.enums import DocumentStatus
from app.workers.base_task import RudixTask
from app.workers.ingestion.deps import current_deps
from app.workers.status_tracking import FailureMarkOutcome


class DocumentTask(RudixTask):
    abstract = True

    def _handle_protected_failure(
        self,
        *,
        document_id: str,
        current_status: str | None,
        error_details: dict[str, Any],
        kwargs: dict[str, Any],
    ) -> None:
        """Keep a deletion/security status intact after a terminal task failure."""
        deps = current_deps()
        deps.log_document_event(
            event="document.processing.failure_status_preserved",
            document_id=document_id,
            request_id=kwargs.get("request_id"),
            organization_id=kwargs.get("organization_id"),
            user_id=kwargs.get("user_id"),
            current_status=current_status,
            error_code=error_details["code"],
        )
        deps.record_worker_audit(
            action="document.task.failure_ignored",
            resource_type="document",
            resource_id=document_id,
            organization_id=kwargs.get("organization_id"),
            user_id=kwargs.get("user_id"),
            request_id=kwargs.get("request_id"),
            metadata={
                "task_name": self.name,
                "status": current_status,
                "error_code": error_details["code"],
            },
        )
        if current_status in (DocumentStatus.quarantined.value, DocumentStatus.blocked.value):
            from app.workers.notification_helper import emit_notification

            emit_notification(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                event_type="upload_failed",
                severity="error",
                title="Document processing failed",
                message="The document could not be indexed. Check the document details for more information.",
                href=f"/documents?highlight={document_id}",
                source_id=document_id,
            )

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        deps = current_deps()
        document_id = kwargs.get("document_id")
        if document_id is None and args:
            document_id = args[0]
        if not isinstance(document_id, str):
            return
        try:
            error_details = details_from_exception(exc)
            owner_task_id = getattr(self.request, "id", None)
            mark = deps.mark_document_failed(
                document_id,
                error_message=encode_document_error(error_details),
                owner_task_id=owner_task_id,
                protected_statuses=TERMINAL_FAILURE_PROTECTED_STATUSES,
            )
            if mark.outcome in (FailureMarkOutcome.superseded, FailureMarkOutcome.not_found):
                # The claim was taken over by another task (or the row is gone);
                # the new holder owns the outcome, so do not report a failure.
                deps.log_document_event(
                    event="document.processing.failure_superseded",
                    document_id=document_id,
                    request_id=kwargs.get("request_id"),
                    organization_id=kwargs.get("organization_id"),
                    user_id=kwargs.get("user_id"),
                    processing_task_id=owner_task_id,
                    error_code=error_details["code"],
                )
                return
            if mark.outcome == FailureMarkOutcome.protected:
                self._handle_protected_failure(
                    document_id=document_id,
                    current_status=mark.current_status,
                    error_details=error_details,
                    kwargs=kwargs,
                )
                return
            deps.log_document_event(
                event="document.processing.failed",
                document_id=document_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=DocumentStatus.failed.value,
                error=str(exc),
                error_stage=error_details["stage"],
                error_code=error_details["code"],
                error_category=error_details["category"],
                retryable=error_details["retryable"],
            )
            deps.record_worker_audit(
                action="document.task.failed",
                resource_type="document",
                resource_id=document_id,
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                request_id=kwargs.get("request_id"),
                metadata={
                    "task_name": self.name,
                    "status": DocumentStatus.failed.value,
                    "error_type": exc.__class__.__name__,
                    "error_code": error_details["code"],
                    "error_category": error_details["category"],
                    "retryable": error_details["retryable"],
                },
            )
            from app.workers.notification_helper import emit_notification

            emit_notification(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                event_type="upload_failed",
                severity="error",
                title="Document processing failed",
                message="The document could not be indexed. Check the document details for more information.",
                href=f"/documents?highlight={document_id}",
                source_id=document_id,
            )
            from app.workers.email_helper import emit_upload_failure_email

            emit_upload_failure_email(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                document_id=document_id,
                error_summary=error_details.get("stage"),
            )
        except Exception:
            return


class DocumentDeleteTask(DocumentTask):
    """Task base class for document deletion — leaves document in delete_requested on terminal failure."""

    abstract = True

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        deps = current_deps()
        document_id = kwargs.get("document_id")
        if document_id is None and args:
            document_id = args[0]
        if not isinstance(document_id, str):
            return
        try:
            error_details = details_from_exception(exc)
            error_message = f"delete_failed: {encode_document_error(error_details)}"
            # Revert to delete_requested so the admin can retry the cleanup.
            deps.set_document_status(
                document_id,
                status=DocumentStatus.delete_requested,
                error_message=error_message,
            )
            deps.log_document_event(
                event="document.deletion.failed",
                document_id=document_id,
                request_id=kwargs.get("request_id"),
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                status_code=DocumentStatus.delete_requested.value,
                error=str(exc),
                error_stage=error_details["stage"],
                error_code=error_details["code"],
                error_category=error_details["category"],
                retryable=error_details["retryable"],
            )
            deps.record_worker_audit(
                action="document.delete.failed",
                resource_type="document",
                resource_id=document_id,
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                request_id=kwargs.get("request_id"),
                metadata={
                    "task_name": self.name,
                    "status": DocumentStatus.delete_requested.value,
                    "error_type": exc.__class__.__name__,
                    "error_code": error_details["code"],
                    "error_category": error_details["category"],
                    "retryable": error_details["retryable"],
                },
            )
            from app.workers.notification_helper import emit_notification

            emit_notification(
                organization_id=kwargs.get("organization_id"),
                user_id=kwargs.get("user_id"),
                event_type="security_warning",
                severity="error",
                title="Document deletion failed",
                message="Cleanup could not complete. An admin can retry the deletion.",
                href=f"/admin/documents/deletion?highlight={document_id}",
                source_id=document_id,
            )
        except Exception:
            return
