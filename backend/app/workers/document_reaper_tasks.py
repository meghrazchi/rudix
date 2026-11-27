"""Beat-scheduled reaper for documents stuck in ``processing`` (R02-02).

A document is stale when ``COALESCE(processing_started_at, updated_at)`` is older than
``DOCUMENT_PROCESSING_STALE_SECONDS``. Stale rows are released (claim columns cleared,
``processing_reap_count`` incremented) and re-queued as ``documents.process``; rows that
were already re-queued ``DOCUMENT_REAPER_MAX_ATTEMPTS`` times are marked ``failed``.

Known edge: a stalled ``documents.reindex`` run is re-queued as ``documents.process``
with the default chunking profile, because the original task kwargs are not persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.config import settings
from app.core.document_errors import build_document_error_details, encode_document_error
from app.core.logging import log_document_event
from app.core.metrics import record_document_reaped
from app.db.session import maintenance_session
from app.domains.documents.repositories.processing_claims import (
    DocumentProcessingClaimRepository,
)
from app.workers.async_runtime import run_async
from app.workers.base_task import RudixTask
from app.workers.celery_app import celery_app

_claim_repository = DocumentProcessingClaimRepository()

_STALLED_MESSAGE = (
    "Document processing stopped responding and was retried the maximum number of times."
)


@dataclass(frozen=True)
class _ReapedRow:
    document_id: UUID
    organization_id: UUID
    user_id: UUID | None
    reap_count: int


def _stalled_error_message() -> str:
    return encode_document_error(
        build_document_error_details(
            stage="processing",
            code="PROCESSING_STALLED",
            category="infrastructure",
            retryable=True,
            message=_STALLED_MESSAGE,
        )
    )


def _optional_str(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


async def _release_stale_rows(now: datetime) -> tuple[list[_ReapedRow], list[_ReapedRow]]:
    stale_before = now - timedelta(seconds=settings.document_processing_stale_seconds)
    requeue: list[_ReapedRow] = []
    exhausted: list[_ReapedRow] = []
    # Cross-tenant beat task: maintenance session (BYPASSRLS role when configured, R04-08).
    async with maintenance_session() as session:
        async with session.begin():
            rows = await _claim_repository.select_stale_processing(
                session,
                stale_before=stale_before,
                limit=settings.document_reaper_batch_size,
            )
            for row in rows:
                reap_count = int(row.processing_reap_count or 0)
                if reap_count >= settings.document_reaper_max_attempts:
                    if await _claim_repository.mark_reap_exhausted(
                        session,
                        document_id=row.id,
                        now=now,
                        error_message=_stalled_error_message(),
                    ):
                        exhausted.append(
                            _ReapedRow(row.id, row.organization_id, row.uploaded_by_user_id, 0)
                        )
                    continue
                if await _claim_repository.mark_reaped(session, document_id=row.id, now=now):
                    requeue.append(
                        _ReapedRow(
                            row.id,
                            row.organization_id,
                            row.uploaded_by_user_id,
                            reap_count + 1,
                        )
                    )
    return requeue, exhausted


def _requeue(row: _ReapedRow) -> bool:
    document_id = str(row.document_id)
    try:
        celery_app.send_task(
            "documents.process",
            args=[document_id],
            kwargs={
                "organization_id": str(row.organization_id),
                "user_id": _optional_str(row.user_id),
            },
        )
    except Exception as exc:
        # updated_at was bumped, so the row is picked up again after the next stale interval.
        record_document_reaped("enqueue_error")
        log_document_event(
            event="document.processing.reap_enqueue_failed",
            document_id=document_id,
            organization_id=str(row.organization_id),
            outcome="enqueue_error",
            reap_count=row.reap_count,
            error_type=exc.__class__.__name__,
        )
        return False
    record_document_reaped("requeued")
    log_document_event(
        event="document.processing.reaped",
        document_id=document_id,
        organization_id=str(row.organization_id),
        outcome="requeued",
        reap_count=row.reap_count,
    )
    return True


def _report_exhausted(row: _ReapedRow) -> None:
    document_id = str(row.document_id)
    record_document_reaped("failed")
    log_document_event(
        event="document.processing.reap_exhausted",
        document_id=document_id,
        organization_id=str(row.organization_id),
        outcome="failed",
        reap_count=settings.document_reaper_max_attempts,
        error_code="PROCESSING_STALLED",
    )
    from app.workers.notification_helper import emit_notification

    emit_notification(
        organization_id=str(row.organization_id),
        user_id=_optional_str(row.user_id),
        event_type="upload_failed",
        severity="error",
        title="Document processing failed",
        message=(
            "The document could not be indexed. Check the document details for more information."
        ),
        href=f"/documents?highlight={document_id}",
        source_id=document_id,
    )


async def _reap_stale_documents_async() -> dict[str, int]:
    now = datetime.now(UTC)
    requeue, exhausted = await _release_stale_rows(now)
    # Enqueue only after the release committed, so the new task can claim the row.
    enqueue_errors = 0
    requeued = 0
    for row in requeue:
        if _requeue(row):
            requeued += 1
        else:
            enqueue_errors += 1
    for row in exhausted:
        _report_exhausted(row)
    return {"requeued": requeued, "failed": len(exhausted), "enqueue_errors": enqueue_errors}


@celery_app.task(name="documents.reap_stale", bind=True, base=RudixTask, ignore_result=True)
def reap_stale_documents(self: RudixTask) -> dict[str, int]:
    """Release documents stuck in processing and re-queue them, or fail them when exhausted."""
    return run_async(_reap_stale_documents_async())
