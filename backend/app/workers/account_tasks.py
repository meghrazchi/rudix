"""Account beat and background tasks (0.9.0).

* ``auth.tokens.purge_expired`` (S1, daily 03:25 UTC on the default queue): deletes
  single-use account tokens that expired, or were consumed, more than
  ``AUTH_ONE_TIME_TOKEN_RETENTION_HOURS`` ago. Tokens carry no tenant data worth keeping
  once unusable. Cross-tenant, so it uses ``maintenance_session()``; idempotent (a rerun
  finds nothing left to delete).

A1 adds its recovery mail tasks below its marker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import maintenance_session
from app.domains.auth.services import one_time_tokens
from app.workers.async_runtime import run_async
from app.workers.base_task import RudixTask
from app.workers.celery_app import celery_app

PURGE_EXPIRED_TOKENS_TASK = "auth.tokens.purge_expired"

_logger = get_logger("events.auth.tokens")


async def purge_expired_tokens(now: datetime) -> dict[str, Any]:
    cutoff = now - timedelta(hours=settings.auth_one_time_token_retention_hours)
    async with maintenance_session() as session:
        purged = await one_time_tokens.purge_expired(session, cutoff)
        await session.commit()
    _logger.info("auth.tokens.purge_completed", purged=purged, cutoff=cutoff.isoformat())
    return {"purged": purged, "cutoff": cutoff.isoformat()}


@celery_app.task(name=PURGE_EXPIRED_TOKENS_TASK, bind=True, base=RudixTask, ignore_result=True)
def purge_expired_tokens_task(self: RudixTask) -> dict[str, Any]:
    """Delete unusable single-use account tokens past the retention window."""
    return run_async(purge_expired_tokens(datetime.now(UTC)))


# v090-A1
