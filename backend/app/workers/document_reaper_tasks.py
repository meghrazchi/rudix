"""Beat-scheduled reaper for documents stuck in ``processing`` (R02-02).

A document is stale when ``COALESCE(processing_started_at, updated_at)`` is older than
``DOCUMENT_PROCESSING_STALE_SECONDS``. Stale rows are released (claim columns cleared,
``processing_reap_count`` incremented) and re-queued as ``documents.process``; rows that
were already re-queued ``DOCUMENT_REAPER_MAX_ATTEMPTS`` times are marked ``failed``.

The re-queue passes ``resume_run_id`` = the document's latest unfinished run (from
``document_processing_stages``), so the new claim continues that run after its last
completed stage (OCR and finished embedding batches are not redone; R06-01 part 2).

Known edge: a stalled ``documents.reindex`` run is re-queued as ``documents.process``
with the default chunking profile, because the original task kwargs are not persisted.

``documents.stage_artifacts.purge`` (daily) deletes stage artifacts older than
``INGEST_STAGE_ARTIFACT_TTL_HOURS`` of documents that are not processing: runs that failed
for good, or were abandoned, keep no copies of document text beyond the TTL.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, select

from app.application.realtime.publisher import record_realtime_event
from app.core.config import settings
from app.core.document_errors import build_document_error_details, encode_document_error
from app.core.logging import log_document_event
from app.core.metrics import record_document_reaped
from app.db.session import maintenance_session
from app.domains.documents.repositories.processing_claims import (
    DocumentProcessingClaimRepository,
)
from app.domains.realtime.events import document_status_events
from app.models.document import Document
from app.models.document_processing import DocumentProcessingStage, DocumentStageArtifact
from app.models.enums import DocumentStatus
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
    resume_run_id: str | None = None


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


async def _latest_unfinished_run(session: Any, document_id: UUID) -> str | None:
    """Most recently active run of the document whose finalize row is not completed."""
    stage = DocumentProcessingStage
    finished = (
        select(stage.run_id)
        .where(
            stage.document_id == document_id,
            stage.stage == "finalize",
            stage.status == "completed",
        )
        .scalar_subquery()
    )
    row = (
        await session.execute(
            select(stage.run_id)
            .where(stage.document_id == document_id, stage.run_id.not_in(finished))
            .group_by(stage.run_id)
            .order_by(func.max(stage.updated_at).desc())
            .limit(1)
        )
    ).first()
    return str(row[0]) if row is not None else None


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
                        # Core UPDATE: the ORM observer cannot see it (R07-07).
                        record_realtime_event(
                            session,
                            document_status_events(
                                organization_id=row.organization_id,
                                document_id=row.id,
                                status=DocumentStatus.failed.value,
                                uploader_id=row.uploaded_by_user_id,
                            ),
                        )
                    continue
                if await _claim_repository.mark_reaped(session, document_id=row.id, now=now):
                    requeue.append(
                        _ReapedRow(
                            row.id,
                            row.organization_id,
                            row.uploaded_by_user_id,
                            reap_count + 1,
                            await _latest_unfinished_run(session, row.id),
                        )
                    )
    return requeue, exhausted


def _requeue(row: _ReapedRow) -> bool:
    document_id = str(row.document_id)
    kwargs: dict[str, Any] = {
        "organization_id": str(row.organization_id),
        "user_id": _optional_str(row.user_id),
    }
    if row.resume_run_id is not None:
        kwargs["resume_run_id"] = row.resume_run_id
    try:
        celery_app.send_task("documents.process", args=[document_id], kwargs=kwargs)
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
        resumed=row.resume_run_id is not None,
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


async def _purge_stage_artifacts_async(now: datetime | None = None) -> dict[str, int]:
    """Delete stage artifacts past the TTL of documents that are not processing."""
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=settings.ingest_stage_artifact_ttl_hours)
    artifact = DocumentStageArtifact
    processing = select(Document.id).where(
        Document.id == artifact.document_id,
        Document.status == DocumentStatus.processing.value,
    )
    # Cross-tenant beat task: maintenance session (BYPASSRLS role when configured).
    async with maintenance_session() as session, session.begin():
        result = await session.execute(
            delete(artifact)
            .where(and_(artifact.created_at < cutoff, ~processing.exists()))
            .execution_options(synchronize_session=False)
        )
    deleted = int(getattr(result, "rowcount", 0) or 0)
    log_document_event(event="document.stage_artifacts.purged", deleted_count=deleted)
    return {"deleted": deleted}


@celery_app.task(
    name="documents.stage_artifacts.purge", bind=True, base=RudixTask, ignore_result=True
)
def purge_stage_artifacts(self: RudixTask) -> dict[str, int]:
    """Daily: drop stage artifacts older than INGEST_STAGE_ARTIFACT_TTL_HOURS (R06-01)."""
    return run_async(_purge_stage_artifacts_async())
