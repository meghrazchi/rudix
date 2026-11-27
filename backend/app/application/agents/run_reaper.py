"""Beat task body of ``agents.runs.reap``: recover runs whose worker died (R06-13).

Every ``AGENT_RUN_REAP_INTERVAL_SECONDS`` (60 s) the reaper reads up to
``AGENT_RUN_REAP_BATCH_SIZE`` runs that are ``running`` with an expired lease, through
``maintenance_session()`` (all organisations), ``FOR UPDATE SKIP LOCKED`` so two reapers
never handle the same run:

- ``resume_count`` below ``AGENT_RUN_MAX_RESUMES``: the run goes back to ``queued`` with
  ``resume_count + 1`` and an outbox row for ``agents.run.execute`` (dedupe key per resume)
  in the same transaction; the new task resumes after the last completed step;
- otherwise the run fails with ``worker_lost``.

Each transition is a conditional ``UPDATE`` (still running, lease still expired), so a task
that renewed its lease meanwhile keeps its run. Runs executed inline never hold a lease and
are never touched.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.application import outbox
from app.application.agents.run_submission import EXECUTE_TASK
from app.application.agents.worker_execution import deps
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_agent_run_reaped
from app.domains.agents.repositories import AgentRunWorkerRepository

logger = get_logger("agent.reaper")
_worker = AgentRunWorkerRepository()


async def reap_expired_runs(
    *, now: datetime | None = None, session_factory: Callable[[], Any] | None = None
) -> dict[str, int]:
    current = now or datetime.now(tz=UTC)
    counts = {"requeued": 0, "failed": 0}
    factory = session_factory or deps.maintenance_factory
    async with factory() as session:
        expired = await _worker.list_expired(
            session, now=current, limit=settings.agent_run_reap_batch_size
        )
        for lease in expired:
            if lease.resume_count >= settings.agent_run_max_resumes:
                if await _worker.fail_lost(session, run_id=lease.run_id, now=current):
                    counts["failed"] += 1
                    record_agent_run_reaped("failed")
                    logger.warning(
                        "agent.reaper.worker_lost",
                        run_id=str(lease.run_id),
                        organization_id=str(lease.organization_id),
                        resume_count=lease.resume_count,
                        error_code="worker_lost",
                    )
                continue
            if not await _worker.requeue_expired(session, run_id=lease.run_id, now=current):
                continue
            await outbox.enqueue(
                session,
                organization_id=lease.organization_id,
                task_name=EXECUTE_TASK,
                kwargs={
                    "run_id": str(lease.run_id),
                    "organization_id": str(lease.organization_id),
                },
                queue=settings.celery_queue_agents,
                dedupe_key=f"{EXECUTE_TASK}:{lease.run_id}:resume:{lease.resume_count + 1}",
            )
            counts["requeued"] += 1
            record_agent_run_reaped("requeued")
            logger.info(
                "agent.reaper.requeued",
                run_id=str(lease.run_id),
                organization_id=str(lease.organization_id),
                resume_count=lease.resume_count + 1,
            )
        await session.commit()
        await outbox.publish_after_commit(session)
    if counts["requeued"] or counts["failed"]:
        logger.info("agent.reaper.completed", **counts)
    return counts
