"""Latency budget policies of the chat pipeline (R05-04).

``CHAT_TOTAL_DEADLINE_MS`` sets a deadline for the whole run and ``CHAT_STAGE_BUDGET_*_MS``
give single optional steps their own budget (0 = off). Only the optional steps below can be
cut short; each has a fixed degraded action:

=============  ===========================  =======================================
step           budget setting               degraded action
=============  ===========================  =======================================
rewrite        chat_stage_budget_rewrite    ``original_question`` (no rewriting)
graph          chat_stage_budget_graph      ``vector_only`` (graph branch dropped)
rerank         chat_stage_budget_rerank     ``original_order`` (retrieval order)
conflict       chat_stage_budget_conflict   ``skipped``
tree_search    chat_stage_budget_tree_      ``single_generation``
               search
verify         chat_stage_budget_verify     ``skipped`` (standard mode) or
                                            ``answer_withheld`` (strict mode)
refine         chat_stage_budget_refine     ``skipped`` (critic and refiner)
=============  ===========================  =======================================

Required stages are never cut short: authorize, guard, vector retrieval, generate, citation
validation, and persist run to completion whatever the deadline. In strict grounded
verification an exhausted verify budget withholds the answer (not found, verification
failed); unverified text is never returned.

Every skip appends a ``StageDegradationRecord`` to ``ctx.stage_degradations`` (trust metadata
``stage_degradations``), increments ``rudix_chat_stage_skipped_total{stage,reason}``, and
logs ``query.stage.degraded`` with the stage, reason, and action only.

With every budget at 0 and no deadline nothing here wraps a call, so behaviour is unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Final, Literal

from app.application.chat.pipeline.context import ChatContext
from app.core.config import settings
from app.core.logging import log_query_event
from app.core.metrics import record_chat_stage_skipped
from app.domains.chat.schemas.trust_metadata import StageDegradationRecord

DegradationReason = Literal["deadline", "budget", "error"]

REQUIRED_STAGES: Final = frozenset(
    {"authorize", "guard", "retrieve", "generate", "citation_validation", "persist"}
)


@dataclass(frozen=True)
class StagePolicy:
    stage: str
    budget_setting: str
    action: str


OPTIONAL_STAGE_POLICIES: Final[dict[str, StagePolicy]] = {
    policy.stage: policy
    for policy in (
        StagePolicy("rewrite", "chat_stage_budget_rewrite_ms", "original_question"),
        StagePolicy("graph", "chat_stage_budget_graph_ms", "vector_only"),
        StagePolicy("rerank", "chat_stage_budget_rerank_ms", "original_order"),
        StagePolicy("conflict", "chat_stage_budget_conflict_ms", "skipped"),
        StagePolicy("tree_search", "chat_stage_budget_tree_search_ms", "single_generation"),
        StagePolicy("verify", "chat_stage_budget_verify_ms", "skipped"),
        StagePolicy("refine", "chat_stage_budget_refine_ms", "skipped"),
    )
}
ACTION_ANSWER_WITHHELD: Final = "answer_withheld"


@dataclass(frozen=True)
class StageBudget:
    """Seconds an optional step may take, and which limit is binding."""

    seconds: float
    reason: DegradationReason


def start_deadline(ctx: ChatContext, clock: Callable[[], float] = perf_counter) -> None:
    """Set the run deadline from ``CHAT_TOTAL_DEADLINE_MS`` (0 leaves it off)."""
    total_ms = settings.chat_total_deadline_ms
    ctx.budget_deadline = clock() + total_ms / 1000 if total_ms > 0 else None


def stage_budget(
    ctx: ChatContext, stage: str, clock: Callable[[], float] = perf_counter
) -> StageBudget | None:
    """The budget of optional ``stage``, or ``None`` when neither limit applies."""
    if stage in REQUIRED_STAGES:
        return None
    policy = OPTIONAL_STAGE_POLICIES[stage]
    own_ms = int(getattr(settings, policy.budget_setting))
    own = own_ms / 1000 if own_ms > 0 else None
    remaining = None if ctx.budget_deadline is None else max(0.0, ctx.budget_deadline - clock())
    if own is None and remaining is None:
        return None
    if remaining is not None and (own is None or remaining < own):
        return StageBudget(seconds=remaining, reason="deadline")
    assert own is not None
    return StageBudget(seconds=own, reason="budget")


def record_stage_degradation(
    ctx: ChatContext,
    stage: str,
    reason: DegradationReason,
    action: str | None = None,
) -> StageDegradationRecord:
    """Record one skipped or degraded optional step (trust metadata, metric, log)."""
    policy = OPTIONAL_STAGE_POLICIES.get(stage)
    resolved_action = action or (policy.action if policy is not None else "skipped")
    record = StageDegradationRecord(stage=stage, reason=reason, action=resolved_action)
    ctx.stage_degradations.append(record)
    record_chat_stage_skipped(stage, reason)
    log_query_event(
        event="query.stage.degraded",
        organization_id=str(ctx.request.organization_id),
        user_id=str(ctx.request.user_id),
        job_id=ctx.job_id or None,
        stage=stage,
        reason=reason,
        action=resolved_action,
        transport=ctx.request.transport,
    )
    return record


def record_runner_degradation(ctx: ChatContext, stage: str, reason: str) -> None:
    """``StageRunner`` hook: keep S1's record and add the trust-metadata record."""
    ctx.degradations.append({"stage": stage, "reason": reason})
    record_stage_degradation(ctx, stage, "deadline" if reason == "deadline" else "budget")


@dataclass(frozen=True)
class BudgetOutcome[T]:
    completed: bool
    value: T | None = None
    reason: DegradationReason | None = None


async def run_with_budget[T](
    ctx: ChatContext,
    stage: str,
    call: Callable[[], Awaitable[T]],
    *,
    action: str | None = None,
    record: bool = True,
) -> BudgetOutcome[T]:
    """Await ``call()`` within the stage budget; on timeout record the degradation.

    Without a budget the call is awaited directly, so its errors propagate untouched.
    An already exhausted budget skips the call without starting it.
    """
    budget = stage_budget(ctx, stage)
    if budget is None:
        return BudgetOutcome(completed=True, value=await call())
    try:
        if budget.seconds <= 0:
            raise TimeoutError
        value = await asyncio.wait_for(call(), timeout=budget.seconds)
    except TimeoutError:
        if record:
            record_stage_degradation(ctx, stage, budget.reason, action)
        return BudgetOutcome(completed=False, reason=budget.reason)
    return BudgetOutcome(completed=True, value=value)
