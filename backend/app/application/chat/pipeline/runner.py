"""Stage runner of the chat pipeline (R05-01).

Runs the stages in order and records ``rudix_chat_stage_seconds{stage}``. Per-stage timeouts
and the run deadline are hooks with defaults off (B2 sets the policies): a stage that runs
out of time is recorded as a degradation and either skipped (``optional`` stages) or
re-raised. Background tasks a stage registers on the context are cancelled when the run
ends, whatever the outcome.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from time import perf_counter
from typing import Protocol

from app.application.chat.pipeline.context import ChatContext
from app.core.logging import log_query_event
from app.core.metrics import CHAT_STAGE_SECONDS


class Stage(Protocol):
    name: str
    # False: the stage is skipped once a stage produced the final answer (ctx.terminal).
    runs_when_terminal: bool
    # True: a timeout skips the stage instead of failing the run.
    optional: bool

    async def run(self, ctx: ChatContext) -> None: ...


DegradationHook = Callable[[ChatContext, str, str], None]
# Called after every stage in order, whether it ran or was skipped (R05-02 phase ends).
AfterStageHook = Callable[["Stage", ChatContext], Awaitable[None]]


class ChatStageTimeoutError(TimeoutError):
    def __init__(self, stage: str) -> None:
        super().__init__(f"chat pipeline stage {stage} timed out")
        self.stage = stage


def record_degradation(ctx: ChatContext, stage: str, reason: str) -> None:
    """Default hook: keep the stage and reason on the context and log them (no request text)."""
    ctx.degradations.append({"stage": stage, "reason": reason})
    log_query_event(
        event="query.stage.degraded",
        organization_id=str(ctx.request.organization_id),
        user_id=str(ctx.request.user_id),
        job_id=ctx.job_id or None,
        stage=stage,
        reason=reason,
        transport=ctx.request.transport,
    )


class StageRunner:
    def __init__(
        self,
        stages: Sequence[Stage],
        *,
        timeouts: dict[str, float | None] | None = None,
        degradation_hook: DegradationHook = record_degradation,
        clock: Callable[[], float] = perf_counter,
        after_stage: AfterStageHook | None = None,
    ) -> None:
        self._stages = list(stages)
        self._after_stage = after_stage
        self._timeouts = dict(timeouts or {})
        self._degradation_hook = degradation_hook
        self._clock = clock

    @property
    def stages(self) -> list[Stage]:
        return list(self._stages)

    def _timeout_for(self, stage: Stage, ctx: ChatContext) -> float | None:
        timeout = self._timeouts.get(stage.name)
        if ctx.deadline is None:
            return timeout
        remaining = max(0.0, ctx.deadline - self._clock())
        return remaining if timeout is None else min(timeout, remaining)

    async def run(self, ctx: ChatContext) -> ChatContext:
        try:
            for stage in self._stages:
                if not (ctx.terminal and not stage.runs_when_terminal):
                    await self._run_stage(stage, ctx)
                if self._after_stage is not None:
                    await self._after_stage(stage, ctx)
        finally:
            await self._cancel_background_tasks(ctx)
        return ctx

    async def _run_stage(self, stage: Stage, ctx: ChatContext) -> None:
        timeout = self._timeout_for(stage, ctx)
        started = perf_counter()
        try:
            if timeout is None:
                # No budget: errors of the stage propagate untouched (today's behaviour).
                await stage.run(ctx)
                return
            try:
                if timeout <= 0:
                    raise TimeoutError
                await asyncio.wait_for(stage.run(ctx), timeout=timeout)
            except ChatStageTimeoutError:
                raise
            except TimeoutError as exc:
                reason = "deadline" if ctx.deadline is not None else "timeout"
                self._degradation_hook(ctx, stage.name, reason)
                if not stage.optional:
                    raise ChatStageTimeoutError(stage.name) from exc
        finally:
            CHAT_STAGE_SECONDS.labels(stage=stage.name).observe(perf_counter() - started)

    @staticmethod
    async def _cancel_background_tasks(ctx: ChatContext) -> None:
        pending = [task for task in ctx.background_tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        ctx.background_tasks.clear()
