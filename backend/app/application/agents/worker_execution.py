"""Body of the ``agents.run.execute`` and ``agents.run.resume`` tasks (R06-13).

``RudixTask.__call__`` has bound the tenant named by ``organization_id``. A task then:

1. reads the run in that organisation; a run that exists only in another organisation
   raises ``TenantMismatchError`` before any write (contract 4.2.7);
2. (resume) checks that the approval is ``approved`` and adds it to the snapshot's
   ``approval_ids`` under its tool name;
3. takes the lease with one conditional ``UPDATE`` (``queued``, or ``running`` with an
   expired lease or this task id as owner) and commits;
4. rebuilds the principal from the database: the user must be active and still a member
   of the run's organisation, with a role that may start runs and that every planned tool
   accepts. Otherwise the run fails with ``principal_revoked``;
5. runs or resumes the run (``AgentRuntime.execute_queued``); every step commits and
   renews the lease; authorization, budgets, redaction, and safe errors stay inside the
   runtime and the tool executor exactly as inline;
6. clears the lease and commits. A run is ``running`` only while a task holds the lease.

An unexpected exception fails the run with ``internal_error`` (the class name is logged,
never the message). When even that write fails, the exception is re-raised as transient,
so Celery retries; the lease then expires and ``agents.runs.reap`` recovers the run.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_agent_run_task
from app.db.tenant_context import bind_session_tenant
from app.domains.agents.repositories import (
    AgentRunRepository,
    AgentRunWorkerRepository,
    LeaseLostError,
    RunCancelledElsewhereError,
)
from app.domains.agents.schemas import AgentRuntimeRequest, AgentRuntimeResult
from app.domains.agents.services.run_stream import (
    RUN_CANCELLED,
    RUN_STATUS,
    RunEventSink,
    build_run_events,
    emit_result,
)
from app.domains.agents.services.runtime import AgentRuntime
from app.domains.agents.services.runtime_plan import build_plan
from app.models.agent import AgentRun
from app.models.enums import AgentApprovalStatus, OrganizationRole
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.workers.base_task import TenantMismatchError, TransientTaskError

logger = get_logger("agent.worker")

# Roles that may start an agent run (POST /agent/runs).
RUN_ROLES = frozenset(
    {
        OrganizationRole.owner.value,
        OrganizationRole.admin.value,
        OrganizationRole.member.value,
        OrganizationRole.viewer.value,
    }
)


def _default_session_factory() -> Any:
    from app.db import session as db_session

    return db_session.SessionLocal()


def _default_maintenance_factory() -> Any:
    from app.db.session import maintenance_session

    return maintenance_session()


def _default_redis() -> Any:
    from app.clients.factory import create_redis_client

    try:
        return create_redis_client(settings)
    except Exception:
        return None


_runtime: AgentRuntime | None = None


def _default_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
    return _runtime


@dataclass
class AgentWorkerDeps:
    """Indirections read at call time, so tests substitute sessions, runtime, and Redis."""

    session_factory: Callable[[], Any] = _default_session_factory
    maintenance_factory: Callable[[], Any] = _default_maintenance_factory
    runtime_factory: Callable[[], AgentRuntime] = _default_runtime
    redis_factory: Callable[[], Any] = _default_redis


deps = AgentWorkerDeps()
_runs = AgentRunRepository()
_worker = AgentRunWorkerRepository()


def _uuid(value: Any) -> UUID | None:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _owner_elsewhere(run_id: UUID) -> UUID | None:
    try:
        async with deps.maintenance_factory() as session:
            stmt = select(AgentRun.organization_id).where(AgentRun.id == run_id)
            owner: UUID | None = (await session.execute(stmt)).scalar_one_or_none()
            return owner
    except Exception as exc:
        logger.warning("agent.worker.tenant_lookup_failed", error=exc.__class__.__name__)
        return None


async def rebuild_principal(
    session: AsyncSession, *, run: AgentRun, request: AgentRuntimeRequest, runtime: AgentRuntime
) -> AuthenticatedPrincipal | None:
    """The run's principal with current membership and role, or ``None`` when revoked."""
    if run.user_id is None:
        return None
    user = (await session.execute(select(User).where(User.id == run.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    role = (
        await session.execute(
            select(OrganizationMember.role).where(
                OrganizationMember.organization_id == run.organization_id,
                OrganizationMember.user_id == run.user_id,
            )
        )
    ).scalar_one_or_none()
    normalized = str(role or "").strip().lower()
    if normalized not in RUN_ROLES:
        return None
    for selection in build_plan(request=request):
        spec = runtime._registry.get_spec(selection.tool_name)
        if spec is not None and normalized not in spec.required_roles:
            return None
    snapshot = run.request_snapshot if isinstance(run.request_snapshot, dict) else {}
    submitted = snapshot.get("principal") if isinstance(snapshot.get("principal"), dict) else {}
    return AuthenticatedPrincipal(
        user_id=str(user.id),
        organization_id=str(run.organization_id),
        email=user.email,
        roles=[normalized],
        auth_provider=str((submitted or {}).get("auth_provider") or "worker"),
    )


async def _apply_approval(session: AsyncSession, run: AgentRun, approval_id: UUID) -> bool:
    approval = await _runs.get_agent_approval(
        session, approval_id=approval_id, organization_id=run.organization_id, agent_run_id=run.id
    )
    if approval is None or approval.status != AgentApprovalStatus.approved.value:
        return False
    payload = approval.request_payload_json or {}
    tool_name = payload.get("tool_name") or (run.observations_json or {}).get("pending_tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        return False
    snapshot = dict(run.request_snapshot or {})
    request = dict(snapshot.get("request") or {})
    approvals = dict(request.get("approval_ids") or {})
    approvals[tool_name] = str(approval_id)
    request["approval_ids"] = approvals
    snapshot["request"] = request
    await _worker.set_request_snapshot(
        session, run_id=run.id, organization_id=run.organization_id, snapshot=snapshot
    )
    run.request_snapshot = snapshot
    return True


def _checkpoint(
    session: AsyncSession, run: AgentRun | _RunRef, owner: str, *, commit: bool = True
) -> Callable[[], Awaitable[None]]:
    run_id = run.id if isinstance(run, AgentRun) else run.run_id
    organization_id = run.organization_id

    async def save() -> None:
        await _worker.renew(
            session,
            run_id=run_id,
            organization_id=organization_id,
            owner=owner,
            lease_seconds=settings.agent_run_lease_seconds,
            now=datetime.now(tz=UTC),
        )
        await _guard_cancel(session, run_id=run_id, organization_id=organization_id)
        if commit:
            await session.commit()

    return save


async def _guard_cancel(session: AsyncSession, *, run_id: UUID, organization_id: UUID) -> None:
    """Never commit over a cancel another session committed (POST /agent/runs/{id}/cancel)."""
    if await _worker.cancelled_elsewhere(session, run_id=run_id, organization_id=organization_id):
        raise RunCancelledElsewhereError()


async def _execute(
    session: AsyncSession,
    runtime: AgentRuntime,
    run: AgentRun,
    owner: str,
    events: RunEventSink,
) -> AgentRuntimeResult:
    snapshot = run.request_snapshot or {}
    request_id = snapshot.get("request_id") if isinstance(snapshot.get("request_id"), str) else None
    try:
        request = AgentRuntimeRequest.model_validate(snapshot.get("request"))
    except ValidationError:
        fallback = AgentRuntimeRequest(objective=run.objective or "unreadable request")
        return await runtime.fail_queued(
            session=session,
            run_id=run.id,
            organization_id=run.organization_id,
            user_id=run.user_id,
            request=fallback,
            request_id=request_id,
            code="validation_failed",
            message="The stored agent run request could not be read.",
        )
    principal = await rebuild_principal(session, run=run, request=request, runtime=runtime)
    if principal is None:
        return await runtime.fail_queued(
            session=session,
            run_id=run.id,
            organization_id=run.organization_id,
            user_id=run.user_id,
            request=request,
            request_id=request_id,
            code="principal_revoked",
            message="The user who started this run no longer has the access it needs.",
        )
    return await runtime.execute_queued(
        session=session,
        principal=principal,
        run=run,
        request=request,
        request_id=request_id,
        checkpoint=_checkpoint(session, run, owner),
        events=events,
    )


@dataclass(frozen=True)
class _RunRef:
    """Ids read before the loop: a rollback expires the ORM row."""

    run_id: UUID
    organization_id: UUID
    user_id: UUID | None


async def _fail_unexpected(
    session: AsyncSession, runtime: AgentRuntime, ref: _RunRef, owner: str, events: RunEventSink
) -> AgentRuntimeResult:
    await session.rollback()
    result = await runtime.fail_queued(
        session=session,
        run_id=ref.run_id,
        organization_id=ref.organization_id,
        user_id=ref.user_id,
        request=AgentRuntimeRequest(objective="agent run"),
        request_id=None,
        code="internal_error",
        message="The agent run failed unexpectedly.",
    )
    await _worker.release(
        session, run_id=ref.run_id, organization_id=ref.organization_id, owner=owner
    )
    await session.commit()
    await emit_result(events, result)
    return result


async def _run_locked(
    session: AsyncSession,
    runtime: AgentRuntime,
    redis: Any,
    *,
    run: AgentRun,
    owner: str,
) -> str:
    ref = _RunRef(run_id=run.id, organization_id=run.organization_id, user_id=run.user_id)
    events = build_run_events(
        redis, organization_id=ref.organization_id, run_id=ref.run_id, user_id=ref.user_id
    )
    await events.emit(RUN_STATUS, {"status": "running", "resume_count": run.resume_count})
    try:
        result = await _execute(session, runtime, run, owner, events)
    except LeaseLostError:
        await session.rollback()
        return "lease_lost"
    except RunCancelledElsewhereError:
        return await _honour_cancel(session, ref, owner, events)
    except Exception as exc:
        logger.error(
            "agent.worker.run_failed",
            run_id=str(ref.run_id),
            organization_id=str(ref.organization_id),
            error=exc.__class__.__name__,
        )
        try:
            result = await _fail_unexpected(session, runtime, ref, owner, events)
        except Exception as nested:
            raise TransientTaskError("agent run failure could not be recorded") from nested
        return result.status
    try:
        # The terminal write commits only while this task still holds the lease and no
        # cancel was committed meanwhile.
        await _checkpoint(session, ref, owner, commit=False)()
    except LeaseLostError:
        await session.rollback()
        return "lease_lost"
    except RunCancelledElsewhereError:
        return await _honour_cancel(session, ref, owner, events)
    await _worker.release(
        session, run_id=ref.run_id, organization_id=ref.organization_id, owner=owner
    )
    await session.commit()
    await emit_result(events, result)
    return result.status


async def _honour_cancel(
    session: AsyncSession, ref: _RunRef, owner: str, events: RunEventSink
) -> str:
    """Drop this transaction's writes: the committed cancel stays the run's last state."""
    await session.rollback()
    await _worker.release(
        session, run_id=ref.run_id, organization_id=ref.organization_id, owner=owner
    )
    await session.commit()
    await events.emit(RUN_CANCELLED, {"status": "cancelled"})
    logger.info(
        "agent.worker.cancelled_elsewhere",
        run_id=str(ref.run_id),
        organization_id=str(ref.organization_id),
    )
    return "cancelled"


async def _run_in_session(
    session: AsyncSession,
    *,
    run_id: UUID,
    organization_id: UUID,
    owner: str,
    approval_id: UUID | None,
) -> str:
    run = await _runs.get_agent_run(session, agent_run_id=run_id, organization_id=organization_id)
    if run is None:
        other = await _owner_elsewhere(run_id)
        if other is not None and other != organization_id:
            raise TenantMismatchError()
        return "not_found"
    if not isinstance(run.request_snapshot, dict):
        return "not_runnable"  # an inline run: nothing to execute here
    if approval_id is not None and not await _apply_approval(session, run, approval_id):
        await session.rollback()
        return "not_runnable"
    acquired = await _worker.acquire(
        session,
        run_id=run.id,
        organization_id=organization_id,
        owner=owner,
        lease_seconds=settings.agent_run_lease_seconds,
        now=datetime.now(tz=UTC),
    )
    await session.commit()
    await session.refresh(run)
    if not acquired:
        return "lease_held" if run.status == "running" else "not_runnable"
    runtime = deps.runtime_factory()
    redis = deps.redis_factory()
    try:
        return await _run_locked(session, runtime, redis, run=run, owner=owner)
    finally:
        close = getattr(redis, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:
                pass


async def run_agent_task(
    *,
    task_name: str,
    run_id: Any,
    organization_id: Any,
    owner: str,
    approval_id: Any = None,
) -> dict[str, Any]:
    run_uuid = _uuid(run_id)
    org_uuid = _uuid(organization_id)
    outcome = "not_found"
    if run_uuid is not None and org_uuid is not None:
        async with deps.session_factory() as session:
            bind_session_tenant(session, org_uuid)
            outcome = await _run_in_session(
                session,
                run_id=run_uuid,
                organization_id=org_uuid,
                owner=owner,
                approval_id=_uuid(approval_id) if approval_id is not None else None,
            )
    record_agent_run_task(task_name, outcome)
    logger.info(
        "agent.worker.task_finished",
        task_name=task_name,
        run_id=str(run_id),
        organization_id=str(organization_id),
        outcome=outcome,
    )
    return {"run_id": str(run_id), "status": outcome}
