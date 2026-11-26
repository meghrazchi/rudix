from __future__ import annotations

from collections.abc import Collection, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.documents.repositories.processing_claims import (
    ClaimResult,
    DocumentProcessingClaimRepository,
)
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.models.document import Document
from app.models.enums import DocumentStatus, EvaluationRunStatus
from app.workers.async_runtime import run_async

_document_repository = DocumentRepository()
_evaluation_repository = EvaluationRepository()
_claim_repository = DocumentProcessingClaimRepository()


def _parse_uuid(value: str) -> UUID:
    return UUID(value)


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return run_async(coro)


async def _get_document_status_async(document_id: str) -> str | None:
    parsed_id = _parse_uuid(document_id)
    async with SessionLocal() as session:
        document = await _document_repository.get_document_by_id(session, document_id=parsed_id)
        return document.status if document is not None else None


async def _claim_document_for_processing_async(
    document_id: str,
    *,
    task_id: str,
    force: bool,
    skip_statuses: Collection[str] = (),
    forbidden_statuses: Collection[str] = (),
) -> ClaimResult:
    parsed_id = _parse_uuid(document_id)
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=settings.document_processing_stale_seconds)
    async with SessionLocal() as session:
        async with session.begin():
            return await _claim_repository.claim_for_processing(
                session,
                document_id=parsed_id,
                task_id=task_id,
                now=now,
                stale_before=stale_before,
                force=force,
                skip_statuses=skip_statuses,
                forbidden_statuses=forbidden_statuses,
            )


async def _set_document_status_async(
    document_id: str,
    *,
    status: DocumentStatus,
    error_message: str | None = None,
    clear_processing_claim: bool = False,
    owner_task_id: str | None = None,
) -> bool:
    parsed_id = _parse_uuid(document_id)
    async with SessionLocal() as session:
        async with session.begin():
            if owner_task_id is not None:
                # Lock the row so a concurrent claim cannot slip in between check and write.
                result = await session.execute(
                    select(Document).where(Document.id == parsed_id).with_for_update()
                )
                document = result.scalar_one_or_none()
            else:
                document = await _document_repository.get_document_by_id(
                    session, document_id=parsed_id
                )
            if document is None:
                return False
            if owner_task_id is not None and document.processing_task_id not in (
                None,
                owner_task_id,
            ):
                # Another task took over the claim; do not clobber its run.
                return False

            return await _write_document_status(
                session,
                document,
                status=status,
                error_message=error_message,
                clear_processing_claim=clear_processing_claim,
            )


async def _write_document_status(
    session: AsyncSession,
    document: Document,
    *,
    status: DocumentStatus,
    error_message: str | None,
    clear_processing_claim: bool,
) -> bool:
    claim_pending = clear_processing_claim and (
        document.processing_task_id is not None
        or document.processing_started_at is not None
        or document.processing_reap_count != 0
    )
    # Idempotent transition: avoid touching updated_at when nothing changes.
    if (
        document.status == status.value
        and document.error_message == error_message
        and not claim_pending
    ):
        return True

    updated = await _document_repository.update_document_status(
        session,
        document_id=document.id,
        status=status.value,
        error_message=error_message,
        clear_processing_claim=clear_processing_claim,
    )
    return updated is not None


class FailureMarkOutcome(StrEnum):
    updated = "updated"
    superseded = "superseded"
    protected = "protected"
    not_found = "not_found"


@dataclass(frozen=True)
class FailureMarkResult:
    outcome: FailureMarkOutcome
    current_status: str | None = None


async def _mark_document_failed_async(
    document_id: str,
    *,
    error_message: str | None,
    owner_task_id: str | None,
    protected_statuses: Collection[str],
) -> FailureMarkResult:
    parsed_id = _parse_uuid(document_id)
    async with SessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(Document).where(Document.id == parsed_id).with_for_update()
            )
            document = result.scalar_one_or_none()
            if document is None:
                return FailureMarkResult(FailureMarkOutcome.not_found)
            if owner_task_id is not None and document.processing_task_id not in (
                None,
                owner_task_id,
            ):
                return FailureMarkResult(FailureMarkOutcome.superseded, document.status)
            if document.status in protected_statuses:
                if owner_task_id is not None and document.processing_task_id == owner_task_id:
                    document.processing_task_id = None
                    document.processing_started_at = None
                    document.processing_reap_count = 0
                    await session.flush()
                return FailureMarkResult(FailureMarkOutcome.protected, document.status)
            await _write_document_status(
                session,
                document,
                status=DocumentStatus.failed,
                error_message=error_message,
                clear_processing_claim=True,
            )
            return FailureMarkResult(FailureMarkOutcome.updated, DocumentStatus.failed.value)


async def _get_evaluation_status_async(evaluation_run_id: str) -> str | None:
    parsed_id = _parse_uuid(evaluation_run_id)
    async with SessionLocal() as session:
        evaluation_run = await _evaluation_repository.get_evaluation_run(
            session,
            evaluation_run_id=parsed_id,
        )
        return evaluation_run.status if evaluation_run is not None else None


async def _set_evaluation_status_async(
    evaluation_run_id: str,
    *,
    status: EvaluationRunStatus,
    mark_started: bool = False,
    mark_completed: bool = False,
) -> bool:
    parsed_id = _parse_uuid(evaluation_run_id)
    async with SessionLocal() as session:
        async with session.begin():
            updated = await _evaluation_repository.update_evaluation_run_status(
                session,
                evaluation_run_id=parsed_id,
                status=status.value,
                mark_started=mark_started,
                mark_completed=mark_completed,
            )
        return updated is not None


def get_document_status(document_id: str) -> str | None:
    return _run(_get_document_status_async(document_id))


def set_document_status(
    document_id: str,
    *,
    status: DocumentStatus,
    error_message: str | None = None,
    clear_processing_claim: bool = False,
    owner_task_id: str | None = None,
) -> bool:
    return _run(
        _set_document_status_async(
            document_id,
            status=status,
            error_message=error_message,
            clear_processing_claim=clear_processing_claim,
            owner_task_id=owner_task_id,
        )
    )


def mark_document_failed(
    document_id: str,
    *,
    error_message: str | None,
    owner_task_id: str | None,
    protected_statuses: Collection[str],
) -> FailureMarkResult:
    return _run(
        _mark_document_failed_async(
            document_id,
            error_message=error_message,
            owner_task_id=owner_task_id,
            protected_statuses=protected_statuses,
        )
    )


def claim_document_for_processing(
    document_id: str,
    *,
    task_id: str,
    force: bool,
    skip_statuses: Collection[str] = (),
    forbidden_statuses: Collection[str] = (),
) -> ClaimResult:
    return _run(
        _claim_document_for_processing_async(
            document_id,
            task_id=task_id,
            force=force,
            skip_statuses=skip_statuses,
            forbidden_statuses=forbidden_statuses,
        )
    )


def get_evaluation_status(evaluation_run_id: str) -> str | None:
    return _run(_get_evaluation_status_async(evaluation_run_id))


def set_evaluation_status(
    evaluation_run_id: str,
    *,
    status: EvaluationRunStatus,
    mark_started: bool = False,
    mark_completed: bool = False,
) -> bool:
    return _run(
        _set_evaluation_status_async(
            evaluation_run_id,
            status=status,
            mark_started=mark_started,
            mark_completed=mark_completed,
        )
    )
