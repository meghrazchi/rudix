"""Atomic processing claim and stale-processing reaper queries for documents (R02-02).

A claim is a single conditional ``UPDATE ... RETURNING``. On PostgreSQL READ COMMITTED a
concurrent second claimant blocks on the row lock, re-evaluates the WHERE clause against
the winner's committed row, and matches zero rows, so exactly one claimant wins.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import Row, and_, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.document import Document
from app.models.enums import DocumentStatus

_PROCESSING = DocumentStatus.processing.value

# Statuses from which no legitimate flow runs ``documents.process``.
NON_PROCESSABLE_STATUSES: frozenset[str] = frozenset(
    {
        DocumentStatus.deleting.value,
        DocumentStatus.delete_requested.value,
        DocumentStatus.quarantined.value,
        DocumentStatus.blocked.value,
        DocumentStatus.retained_by_policy.value,
    }
)
# A terminal task failure must never overwrite these with ``failed``.
TERMINAL_FAILURE_PROTECTED_STATUSES: frozenset[str] = NON_PROCESSABLE_STATUSES | {
    DocumentStatus.deleted.value
}
PROCESS_SKIP_STATUSES: frozenset[str] = (
    frozenset({DocumentStatus.indexed.value, DocumentStatus.deleted.value})
    | NON_PROCESSABLE_STATUSES
)
REINDEX_FORBIDDEN_STATUSES: frozenset[str] = frozenset(
    {DocumentStatus.deleted.value, DocumentStatus.deleting.value}
)


class ClaimOutcome(StrEnum):
    claimed = "claimed"
    held = "held"
    not_found = "not_found"


@dataclass(frozen=True)
class ClaimResult:
    outcome: ClaimOutcome
    current_status: str | None = None


def _claim_condition(
    *,
    task_id: str,
    stale_before: datetime,
    force: bool,
    skip_statuses: Collection[str],
) -> ColumnElement[bool]:
    if force:
        return true()
    not_processing = Document.status != _PROCESSING
    if skip_statuses:
        not_processing = and_(not_processing, Document.status.not_in(list(skip_statuses)))
    reclaimable = and_(
        Document.status == _PROCESSING,
        or_(
            Document.processing_task_id == task_id,
            Document.processing_started_at.is_(None),
            Document.processing_started_at < stale_before,
        ),
    )
    return or_(not_processing, reclaimable)


class DocumentProcessingClaimRepository:
    async def claim_for_processing(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        task_id: str,
        now: datetime,
        stale_before: datetime,
        force: bool,
        skip_statuses: Collection[str] = (),
        forbidden_statuses: Collection[str] = (),
    ) -> ClaimResult:
        conditions: list[ColumnElement[bool]] = [Document.id == document_id]
        if forbidden_statuses:
            conditions.append(Document.status.not_in(list(forbidden_statuses)))
        conditions.append(
            _claim_condition(
                task_id=task_id,
                stale_before=stale_before,
                force=force,
                skip_statuses=skip_statuses,
            )
        )
        stmt = (
            update(Document)
            .where(*conditions)
            .values(
                status=_PROCESSING,
                processing_task_id=task_id,
                processing_started_at=now,
                error_message=None,
                updated_at=now,
            )
            .returning(Document.id)
            .execution_options(synchronize_session=False)
        )
        claimed = (await session.execute(stmt)).scalar_one_or_none()
        if claimed is not None:
            return ClaimResult(outcome=ClaimOutcome.claimed, current_status=_PROCESSING)
        current_status = (
            await session.execute(select(Document.status).where(Document.id == document_id))
        ).scalar_one_or_none()
        if current_status is None:
            return ClaimResult(outcome=ClaimOutcome.not_found)
        return ClaimResult(outcome=ClaimOutcome.held, current_status=current_status)

    async def select_stale_processing(
        self,
        session: AsyncSession,
        *,
        stale_before: datetime,
        limit: int,
    ) -> list[Row[Any]]:
        started = func.coalesce(Document.processing_started_at, Document.updated_at)
        stmt = (
            select(
                Document.id,
                Document.organization_id,
                Document.uploaded_by_user_id,
                Document.processing_reap_count,
            )
            .where(Document.status == _PROCESSING, started < stale_before)
            .order_by(started)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await session.execute(stmt)).all())

    async def mark_reaped(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        now: datetime,
    ) -> bool:
        stmt = (
            update(Document)
            .where(Document.id == document_id, Document.status == _PROCESSING)
            .values(
                processing_task_id=None,
                processing_started_at=None,
                processing_reap_count=Document.processing_reap_count + 1,
                updated_at=now,
            )
            .returning(Document.id)
            .execution_options(synchronize_session=False)
        )
        return (await session.execute(stmt)).scalar_one_or_none() is not None

    async def mark_reap_exhausted(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        now: datetime,
        error_message: str,
    ) -> bool:
        stmt = (
            update(Document)
            .where(Document.id == document_id, Document.status == _PROCESSING)
            .values(
                status=DocumentStatus.failed.value,
                error_message=error_message,
                processing_task_id=None,
                processing_started_at=None,
                processing_reap_count=0,
                updated_at=now,
            )
            .returning(Document.id)
            .execution_options(synchronize_session=False)
        )
        return (await session.execute(stmt)).scalar_one_or_none() is not None
