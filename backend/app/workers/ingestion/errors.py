"""Document pipeline errors and small parsing helpers (R06-01; moved from document_tasks)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.core.document_errors import build_document_error_details
from app.workers.base_task import PermanentTaskError, TransientTaskError


class DocumentPipelinePermanentError(PermanentTaskError):
    def __init__(self, *, stage: str, code: str, category: str, message: str) -> None:
        super().__init__(message)
        self.error_details = build_document_error_details(
            stage=stage,
            code=code,
            category=category,
            retryable=False,
            message=message,
        )


class DocumentPipelineTransientError(TransientTaskError):
    def __init__(self, *, stage: str, code: str, category: str, message: str) -> None:
        super().__init__(message)
        self.error_details = build_document_error_details(
            stage=stage,
            code=code,
            category=category,
            retryable=True,
            message=message,
        )


def parse_uuid(value: str) -> UUID:
    return UUID(value)


def parse_optional_uuid(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def safe_duration_ms(*, started_at: datetime, ended_at: datetime) -> int:
    return max(int((ended_at - started_at).total_seconds() * 1000), 0)


def parse_document_id(document_id: str) -> UUID:
    try:
        return parse_uuid(document_id)
    except ValueError as exc:
        raise DocumentPipelinePermanentError(
            stage="resolve_document",
            code="INVALID_DOCUMENT_ID",
            category="validation",
            message=f"Invalid document_id: {document_id}",
        ) from exc


def document_not_found(document_id: str) -> DocumentPipelinePermanentError:
    return DocumentPipelinePermanentError(
        stage="resolve_document",
        code="DOCUMENT_NOT_FOUND",
        category="validation",
        message=f"Document not found: {document_id}",
    )
