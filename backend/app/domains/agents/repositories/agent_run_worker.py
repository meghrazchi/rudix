"""Persistence of worker-executed agent runs: leases, resume, reuse (R06-13).

A run is ``running`` only while a task holds its lease (``lease_owner`` = the Celery task
id, ``lease_expires_at`` in the future). Every lease change is one conditional ``UPDATE``,
so two tasks can never both own a run:

- ``acquire``: from ``queued``, or from ``running`` when the lease expired or the same task
  id holds it (a redelivered message after the worker died);
- ``renew``: only while this owner still holds it;
- ``release``: on exit, only this owner's lease.

Runs executed inline never get a lease, so the reaper and ``acquire`` leave them alone.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentRun, AgentStep, AgentToolCall
from app.models.enums import AgentRunStatus, AgentStepStatus, AgentToolCallStatus


class LeaseLostError(Exception):
    """This task no longer holds the run's lease (it expired and was taken over)."""


@dataclass(frozen=True)
class ExpiredLease:
    run_id: UUID
    organization_id: UUID
    resume_count: int


def _hash_key(idempotency_key: str) -> str:
    # Same hash as AgentRunRepository.create_agent_tool_call stores.
    return hashlib.sha256(idempotency_key.strip().encode("utf-8")).hexdigest()


class AgentRunWorkerRepository:
    async def acquire(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        organization_id: UUID,
        owner: str,
        lease_seconds: int,
        now: datetime,
    ) -> bool:
        running = AgentRunStatus.running.value
        expired_or_own = and_(
            AgentRun.status == running,
            AgentRun.lease_expires_at.is_not(None),
            or_(AgentRun.lease_expires_at < now, AgentRun.lease_owner == owner),
        )
        result = await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.organization_id == organization_id,
                or_(AgentRun.status == AgentRunStatus.queued.value, expired_or_own),
            )
            .values(
                status=running,
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
            .returning(AgentRun.id)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None

    async def renew(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        organization_id: UUID,
        owner: str,
        lease_seconds: int,
        now: datetime,
    ) -> None:
        result = await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.organization_id == organization_id,
                AgentRun.lease_owner == owner,
            )
            .values(lease_expires_at=now + timedelta(seconds=lease_seconds))
            .returning(AgentRun.id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            raise LeaseLostError()

    async def release(
        self, session: AsyncSession, *, run_id: UUID, organization_id: UUID, owner: str
    ) -> None:
        await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.organization_id == organization_id,
                AgentRun.lease_owner == owner,
            )
            .values(lease_owner=None, lease_expires_at=None)
            .execution_options(synchronize_session=False)
        )

    async def read_status(
        self, session: AsyncSession, *, run_id: UUID, organization_id: UUID
    ) -> tuple[str, datetime | None] | None:
        """Current status and cancellation time, read from the database (not the identity
        map), so a worker sees a cancel committed by the API between two steps."""
        row = (
            await session.execute(
                select(AgentRun.status, AgentRun.cancelled_at).where(
                    AgentRun.id == run_id, AgentRun.organization_id == organization_id
                )
            )
        ).first()
        if row is None:
            return None
        return str(row[0]), row[1]

    async def set_request_snapshot(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        organization_id: UUID,
        snapshot: dict[str, Any],
    ) -> None:
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
            .values(request_snapshot=snapshot)
            .execution_options(synchronize_session=False)
        )

    async def reset_step_for_retry(
        self,
        session: AsyncSession,
        *,
        step: AgentStep,
        inputs: dict[str, Any],
        started_at: datetime,
    ) -> AgentStep:
        """Reuse a step row a previous task left running or waiting for approval."""
        step.status = AgentStepStatus.running.value
        step.inputs_json = inputs
        step.error_message = None
        step.error_details_json = {}
        step.started_at = started_at
        step.completed_at = None
        step.duration_ms = None
        await session.flush()
        return step

    async def find_succeeded_tool_call(
        self,
        session: AsyncSession,
        *,
        agent_run_id: UUID,
        organization_id: UUID,
        idempotency_key: str,
    ) -> AgentToolCall | None:
        """The completed call with this key (idx_agent_tool_calls_run_idem), if any."""
        result = await session.execute(
            select(AgentToolCall)
            .where(
                AgentToolCall.agent_run_id == agent_run_id,
                AgentToolCall.organization_id == organization_id,
                AgentToolCall.idempotency_key_hash == _hash_key(idempotency_key),
                AgentToolCall.status == AgentToolCallStatus.succeeded.value,
            )
            .order_by(AgentToolCall.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_expired(
        self, session: AsyncSession, *, now: datetime, limit: int
    ) -> list[ExpiredLease]:
        rows = await session.execute(
            select(AgentRun.id, AgentRun.organization_id, AgentRun.resume_count)
            .where(
                AgentRun.status == AgentRunStatus.running.value,
                AgentRun.lease_expires_at.is_not(None),
                AgentRun.lease_expires_at < now,
            )
            .order_by(AgentRun.lease_expires_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [
            ExpiredLease(run_id=row[0], organization_id=row[1], resume_count=int(row[2] or 0))
            for row in rows.all()
        ]

    async def requeue_expired(self, session: AsyncSession, *, run_id: UUID, now: datetime) -> bool:
        result = await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == AgentRunStatus.running.value,
                AgentRun.lease_expires_at < now,
            )
            .values(
                status=AgentRunStatus.queued.value,
                lease_owner=None,
                lease_expires_at=None,
                resume_count=AgentRun.resume_count + 1,
                updated_at=now,
            )
            .returning(AgentRun.id)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None

    async def fail_lost(self, session: AsyncSession, *, run_id: UUID, now: datetime) -> bool:
        result = await session.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == AgentRunStatus.running.value,
                AgentRun.lease_expires_at < now,
            )
            .values(
                status=AgentRunStatus.failed.value,
                lease_owner=None,
                lease_expires_at=None,
                completed_at=now,
                error_message="The worker running this agent run was lost.",
                error_details_json={"code": "worker_lost", "details": {}},
                updated_at=now,
            )
            .returning(AgentRun.id)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None
