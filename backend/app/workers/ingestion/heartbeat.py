"""Document heartbeats of a processing run (R06-01 part 2).

The reaper treats a document as stalled when ``COALESCE(processing_started_at,
updated_at)`` is older than ``DOCUMENT_PROCESSING_STALE_SECONDS``. A long run (many pages,
many embed batches, a chain waiting in queues) refreshes ``processing_started_at`` at the
start of every stage and after every ``INGEST_HEARTBEAT_EVERY_PARTS`` artifact parts or
embed batches, only while ``processing_task_id`` still equals the run's claim token, so a
superseded run never keeps the new holder's claim alive.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document import Document
from app.workers.ingestion.context import StageContext

logger = get_logger("worker.ingestion")


async def heartbeat_document(ctx: StageContext) -> bool:
    """Refresh ``processing_started_at``; True when this run still holds the claim."""
    if not ctx.options.persist_document_state or ctx.claim_token is None:
        return False
    stmt = (
        update(Document)
        .where(Document.id == ctx.document_id, Document.processing_task_id == ctx.claim_token)
        .values(processing_started_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    try:
        async with ctx.deps.SessionLocal() as session, session.begin():
            result = await session.execute(stmt)
    except Exception as exc:
        # A missed heartbeat only lets the reaper act sooner; never fail the stage for it.
        logger.warning(
            "ingestion.heartbeat_failed",
            document_id=ctx.document_id_str,
            run_id=ctx.run_id,
            error_type=type(exc).__name__,
        )
        return False
    ctx.parts_since_heartbeat = 0
    return bool(getattr(result, "rowcount", 0))


async def note_parts(ctx: StageContext, parts: int) -> None:
    """Count written artifact parts or embed batches; heartbeat every N of them."""
    ctx.parts_since_heartbeat += max(parts, 0)
    if ctx.parts_since_heartbeat >= settings.ingest_heartbeat_every_parts:
        await heartbeat_document(ctx)
