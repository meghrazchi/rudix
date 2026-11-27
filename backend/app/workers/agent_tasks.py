from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.logging import get_logger
from app.workers.async_runtime import run_async
from app.workers.base_task import RudixTask
from app.workers.celery_app import celery_app

_logger = get_logger("agent.tasks")


@celery_app.task(name="agents.approvals.expire", bind=True, max_retries=3)
def expire_agent_approvals(self: object) -> dict[str, int]:
    """Mark pending approvals whose expires_at has passed as expired.

    Runs on a short beat schedule so approvals fail safely and deterministically.
    Does not send notifications — callers poll the run status.
    """
    return run_async(_expire_pending())


async def _expire_pending() -> dict[str, int]:
    from app.db.session import maintenance_session
    from app.domains.agents import AgentRunRepository

    repo = AgentRunRepository()
    # Cross-tenant beat task: maintenance session (BYPASSRLS role when configured, R04-08).
    async with maintenance_session() as session:
        async with session.begin():
            expired = await repo.expire_pending_approvals(session)
            failed_runs = await repo.fail_runs_for_expired_approvals(session)

    _logger.info("agents.approvals.expired", count=expired, runs_failed=failed_runs)
    return {"expired": expired, "runs_failed": failed_runs}


# ── Worker execution (R06-13, AGENT_RUN_EXECUTION=worker) ─────────────────────────────


def _lease_owner(task: RudixTask) -> str:
    """The task id: a redelivered message (same id) takes its own lease back."""
    task_id = getattr(task.request, "id", None)
    return str(task_id) if task_id else f"local-{uuid4()}"


@celery_app.task(name="agents.run.execute", bind=True, base=RudixTask, ignore_result=True)
def execute_agent_run(self: RudixTask, run_id: str, organization_id: str) -> dict[str, Any]:
    """Run (or continue) a queued agent run while holding its lease."""
    from app.application.agents.worker_execution import run_agent_task

    return run_async(
        run_agent_task(
            task_name="agents.run.execute",
            run_id=run_id,
            organization_id=organization_id,
            owner=_lease_owner(self),
        )
    )


@celery_app.task(name="agents.run.resume", bind=True, base=RudixTask, ignore_result=True)
def resume_agent_run(
    self: RudixTask, run_id: str, organization_id: str, approval_id: str
) -> dict[str, Any]:
    """Continue a run after its approval was granted (the approval id joins the snapshot)."""
    from app.application.agents.worker_execution import run_agent_task

    return run_async(
        run_agent_task(
            task_name="agents.run.resume",
            run_id=run_id,
            organization_id=organization_id,
            owner=_lease_owner(self),
            approval_id=approval_id,
        )
    )


@celery_app.task(name="agents.runs.reap", bind=True, base=RudixTask, ignore_result=True)
def reap_agent_runs(self: RudixTask) -> dict[str, int]:
    """Re-queue running runs whose lease expired; fail them after AGENT_RUN_MAX_RESUMES."""
    from app.application.agents.run_reaper import reap_expired_runs

    return run_async(reap_expired_runs())
