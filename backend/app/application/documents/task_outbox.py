"""Request-path document task dispatch through the transactional outbox (R06-01 part 2).

``stage`` writes the outbox row in the caller's transaction (commit it with the document
change); ``publish`` runs after that commit and returns the task result or raises the
publish error, so the callers keep their existing deferred and 503 responses. A row whose
immediate publication failed stays ``pending`` and the ``outbox.relay`` beat task publishes
it, so an upload is no longer stuck in ``uploaded`` after a broker outage.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application import outbox


async def stage(
    session: AsyncSession,
    task: Any,
    *,
    task_name: str,
    organization_id: UUID,
    kwargs: dict[str, Any],
    dedupe_key: str | None = None,
) -> UUID | None:
    return await outbox.enqueue(
        session,
        organization_id=organization_id,
        task_name=task_name,
        kwargs=kwargs,
        dedupe_key=dedupe_key,
        task=task,
    )


def result_or_raise(outcomes: list[outbox.PublishOutcome]) -> Any:
    error = outbox.first_error(outcomes)
    if error is not None:
        raise error
    return outbox.first_result(outcomes)


async def dispatch_now(
    session: AsyncSession,
    task: Any,
    *,
    task_name: str,
    organization_id: UUID,
    kwargs: dict[str, Any],
) -> Any:
    """Stage, commit, and publish one dispatch for a route that writes nothing else."""
    await stage(session, task, task_name=task_name, organization_id=organization_id, kwargs=kwargs)
    await session.commit()
    return await publish(session)


async def publish(session: AsyncSession) -> Any:
    """Publish what this session staged; the task result, or the publish error raised."""
    return result_or_raise(await outbox.publish_after_commit(session))
