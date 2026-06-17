from __future__ import annotations

from app.core.logging import get_logger
from app.workers.async_runtime import run_async
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
    from app.db.session import SessionLocal
    from app.domains.agents import AgentRunRepository

    repo = AgentRunRepository()
    async with SessionLocal() as session:
        async with session.begin():
            expired = await repo.expire_pending_approvals(session)

    _logger.info("agents.approvals.expired", count=expired)
    return {"expired": expired}
