"""Usage of a cancelled chat run (R05-03).

When ``chat.cancel`` (WebSocket) or a client disconnect (SSE) cancels a run before stage 10
persisted it, the tokens already spent are written as one ``usage_events`` row with
``event_type = "chat.completion.cancelled"``: the ledger entries (query embedding, any
completed generation) plus the generation attempts that were cut off, using the usage the
provider reported or, when it reported none, chars / 4 estimates (``usage_estimated``).
No chat message is written and the questions quota is not incremented.

The row is written in its own short write session under ``asyncio.shield`` with a timeout,
so a second cancellation cannot interrupt the insert halfway and a slow database cannot
hold the cancelled task.
"""

import asyncio
from typing import Any

from app.application.chat.pipeline.context import ChatContext
from app.core.logging import log_query_event
from app.core.metrics import CHAT_STREAM_CANCELLED_TOTAL

CANCELLED_EVENT_TYPE = "chat.completion.cancelled"
PARTIAL_USAGE_TIMEOUT_SECONDS = 5.0
# Ledger stages that record the answer-generation call itself.
_GENERATION_STAGES = frozenset({"generate", "direct_answers"})


def record_generation_attempts(ctx: ChatContext) -> None:
    """Add the cut-off generation attempts to the ledger (once; a completed generation is
    already recorded by ``apply_llm_result``)."""
    if any(entry.stage in _GENERATION_STAGES for entry in ctx.ledger.entries):
        return
    llm_service = ctx.deps.llm_service
    for attempt in ctx.stream.progress.attempts:
        prompt_tokens, completion_tokens, cached, estimated = attempt.usage()
        ctx.ledger.record(
            "generate",
            attempt.provider_key or None,
            attempt.model,
            prompt_tokens,
            completion_tokens,
            cached_tokens=cached,
            cost_usd=llm_service._estimate_cost(
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
            ),
            estimated=estimated,
        )


def _metadata(ctx: ChatContext) -> dict[str, Any]:
    totals = ctx.ledger.totals()
    chat_session_id = ctx.ids.chat_session_id
    return {
        "cancelled": True,
        "transport": ctx.request.transport,
        "usage_estimated": totals.estimated,
        # A new conversation was never written; only an existing one is referenced.
        "chat_session_id": (
            str(chat_session_id)
            if chat_session_id is not None and not ctx.ids.new_chat_session
            else None
        ),
        "stream_mode": ctx.stream.mode,
        "streamed_chars": len(ctx.stream.streamed_text),
        "generation_attempts": len(ctx.stream.progress.attempts),
        "token_ledger": {
            stage: {
                "prompt_tokens": stage_totals.prompt_tokens,
                "completion_tokens": stage_totals.completion_tokens,
                "estimated": stage_totals.estimated,
            }
            for stage, stage_totals in ctx.ledger.by_stage().items()
        },
    }


async def _write_usage_row(ctx: ChatContext) -> None:
    req = ctx.request
    totals = ctx.ledger.totals()
    generation = [e for e in ctx.ledger.entries if e.stage in _GENERATION_STAGES]
    last = generation[-1] if generation else None
    async with ctx.sessions.write() as db_session:
        await ctx.deps.usage_repository.create_usage_event(
            db_session,
            organization_id=req.organization_id,
            user_id=req.user_id,
            event_type=CANCELLED_EVENT_TYPE,
            model_name=last.model if last is not None else None,
            input_tokens=totals.prompt_tokens,
            output_tokens=totals.completion_tokens,
            cost_usd=totals.cost_usd,
            provider_key=last.provider_key if last is not None else None,
            task_type="chat",
            request_id=req.request_id,
            metadata=_metadata(ctx),
        )
        await db_session.commit()


async def record_cancelled_usage(
    ctx: ChatContext, *, timeout_seconds: float = PARTIAL_USAGE_TIMEOUT_SECONDS
) -> bool:
    """Count the cancellation and write the partial usage row; True when a row was written.

    Called from the ``CancelledError`` handler of the run, so it never raises: failures and
    timeouts are logged (no text, ids and counts only).
    """
    req = ctx.request
    CHAT_STREAM_CANCELLED_TOTAL.labels(transport=req.transport).inc()
    log_query_event(
        event="chat.stream.cancelled",
        organization_id=str(req.organization_id),
        user_id=str(req.user_id),
        request_id=req.request_id,
        transport=req.transport,
        stream_mode=ctx.stream.mode,
    )
    if ctx.persist.assistant_message is not None:
        return False  # stage 10 already committed the answer and its usage
    record_generation_attempts(ctx)
    if not ctx.ledger.entries:
        return False  # nothing was spent yet
    write = asyncio.ensure_future(_write_usage_row(ctx))
    try:
        await asyncio.wait_for(asyncio.shield(write), timeout=timeout_seconds)
    except asyncio.CancelledError:
        # Cancelled again while writing: the shielded insert finishes on its own.
        return False
    except Exception as exc:
        log_query_event(
            event="chat.stream.cancelled_usage_failed",
            organization_id=str(req.organization_id),
            user_id=str(req.user_id),
            request_id=req.request_id,
            transport=req.transport,
            error=exc.__class__.__name__,
        )
        return False
    return True
