from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from app.db.session import SessionLocal
from app.domains.documents.repositories.documents import DocumentRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.models.enums import DocumentStatus, EvaluationRunStatus

_document_repository = DocumentRepository()
_evaluation_repository = EvaluationRepository()
_worker_loop: asyncio.AbstractEventLoop | None = None


def _parse_uuid(value: str) -> UUID:
    return UUID(value)


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    loop = _get_worker_loop()
    return loop.run_until_complete(coro)


async def _get_document_status_async(document_id: str) -> str | None:
    parsed_id = _parse_uuid(document_id)
    async with SessionLocal() as session:
        document = await _document_repository.get_document_by_id(session, document_id=parsed_id)
        return document.status if document is not None else None


async def _set_document_status_async(
    document_id: str,
    *,
    status: DocumentStatus,
    error_message: str | None = None,
) -> bool:
    parsed_id = _parse_uuid(document_id)
    async with SessionLocal() as session:
        async with session.begin():
            document = await _document_repository.get_document_by_id(session, document_id=parsed_id)
            if document is None:
                return False

            # Idempotent transition: avoid touching updated_at when nothing changes.
            if document.status == status.value and document.error_message == error_message:
                return True

            updated = await _document_repository.update_document_status(
                session,
                document_id=parsed_id,
                status=status.value,
                error_message=error_message,
            )
        return updated is not None


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
) -> bool:
    return _run(
        _set_document_status_async(document_id, status=status, error_message=error_message)
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
