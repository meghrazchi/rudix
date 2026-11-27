"""Latency budget of the chat pipeline (R05-04).

A stub provider sleeps for selected prompt kinds; a short stage budget (or total deadline)
must degrade exactly that optional stage, record it in ``stage_degradations``, and count it
in ``rudix_chat_stage_skipped_total``. Required stages always run; strict grounded
verification withholds the answer instead of returning unverified text. With every budget
at 0 (the default) nothing changes, which the golden transcripts also check.

Budgets are 20-50 ms against 2 s sleeps, so the outcomes do not depend on machine speed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from chat_b2_support import B2World, make_world, run_pipeline
from chat_golden_providers import RecordingChatProvider, prompt_kind
from chat_golden_support import SeedDoc
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_golden_transcripts import _answer_with_extra_claim, _verifier_partial

from app.application.chat.pipeline.context import NOT_FOUND_ANSWER, ChatContext
from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.runner import StageRunner
from app.application.chat.pipeline.stages import policies, retrieve
from app.application.chat.pipeline.stages.policies import (
    OPTIONAL_STAGE_POLICIES,
    REQUIRED_STAGES,
    run_with_budget,
    stage_budget,
)
from app.core.config import settings
from app.core.metrics import CHAT_STAGE_SKIPPED_TOTAL
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.domains.ai_response_policy.repositories.ai_response_policy import (
    AiResponsePolicyRepository,
)
from app.domains.chat.schemas.trust_metadata import StageDegradationRecord
from app.domains.chat.services.graph_retrieval_service import GraphRetrievalResult

pytestmark = [pytest.mark.asyncio]

HIGH_RISK_QUESTION = "What does the leave policy require for annual leave?"
TEXT_A = "Employees receive twenty days of annual leave."
TEXT_B = "Contractors receive ten days of annual leave."
SLOW = 2.0


class SleepyProvider(RecordingChatProvider):
    """Sleeps before answering the given prompt kinds."""

    def __init__(self, sleeps: dict[str, float], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.sleeps = sleeps

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        delay = self.sleeps.get(prompt_kind(request.prompt), 0.0)
        if delay:
            await asyncio.sleep(delay)
        return await super().complete(request)


def _skipped(stage: str, reason: str) -> float:
    return float(CHAT_STAGE_SKIPPED_TOTAL.labels(stage=stage, reason=reason)._value.get())


def _records(ctx: ChatContext) -> list[tuple[str, str, str]]:
    return [(r.stage, r.reason, r.action) for r in ctx.stage_degradations]


def _trust_records(ctx: ChatContext) -> list[tuple[str, str, str]]:
    trust = ctx.persist.trust_metadata
    assert trust is not None
    return [(r.stage, r.reason, r.action) for r in trust.stage_degradations]


async def _world(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    sleeps: dict[str, float],
    *,
    two_docs: bool = False,
    responders: dict[str, Any] | None = None,
) -> B2World:
    docs = (
        [SeedDoc("b2-dl-a", TEXT_A, 0.93), SeedDoc("b2-dl-b", TEXT_B, 0.88)]
        if two_docs
        else [SeedDoc("b2-dl-a", TEXT_A, 0.93)]
    )
    provider = SleepyProvider(sleeps, responders=responders)
    return await make_world(db_session, monkeypatch, docs=docs, provider=provider)


# ---------------------------------------------------------------------------
# Defaults: nothing is wrapped
# ---------------------------------------------------------------------------


async def test_defaults_set_no_deadline_and_no_budget(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.chat_total_deadline_ms == 0
    world = await _world(db_session, monkeypatch, {})

    ctx = await run_pipeline(db_session, world.principal, rerank=True)

    assert ctx.budget_deadline is None
    assert all(stage_budget(ctx, stage) is None for stage in OPTIONAL_STAGE_POLICIES)
    assert ctx.stage_degradations == [] and _trust_records(ctx) == []
    assert ctx.retrieval.rerank_applied is True


async def test_required_stages_never_get_a_budget() -> None:
    assert {"authorize", "guard", "retrieve", "generate", "persist"} <= REQUIRED_STAGES
    assert not REQUIRED_STAGES & set(OPTIONAL_STAGE_POLICIES)


# ---------------------------------------------------------------------------
# Optional stages degrade
# ---------------------------------------------------------------------------


async def test_exceeded_rerank_budget_keeps_the_retrieval_order_and_is_recorded(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_stage_budget_rerank_ms", 30)
    world = await _world(db_session, monkeypatch, {"rerank": SLOW}, two_docs=True)
    before = _skipped("rerank", "budget")

    ctx = await run_pipeline(db_session, world.principal, rerank=True)

    assert _records(ctx) == [("rerank", "budget", "original_order")]
    assert _trust_records(ctx) == _records(ctx)
    assert _skipped("rerank", "budget") == before + 1
    assert ctx.retrieval.rerank_applied is False
    assert [c.rerank_score for c in ctx.retrieval.selected_chunks] == [None, None]
    # Required stages still ran: an answer was generated and persisted.
    assert world.calls("answer") == 1 and ctx.generation.not_found is False
    assert ctx.persist.assistant_message is not None


async def test_total_deadline_skips_optional_stages_but_not_required_ones(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_total_deadline_ms", 1)
    world = await _world(db_session, monkeypatch, {"answer": 0.05}, two_docs=True)
    original_start = policies.start_deadline

    def expired_deadline(
        ctx: ChatContext, clock: Callable[[], float] = policies.perf_counter
    ) -> None:
        original_start(ctx, clock)
        assert ctx.budget_deadline is not None
        ctx.budget_deadline -= 10.0  # already passed when the first optional step starts

    monkeypatch.setattr("app.application.chat.pipeline.pipeline.start_deadline", expired_deadline)
    before = _skipped("rerank", "deadline")

    ctx = await run_pipeline(db_session, world.principal, rerank=True)

    assert _records(ctx) == [("rerank", "deadline", "original_order")]
    assert world.calls("rerank") == 0  # an exhausted budget never starts the call
    assert _skipped("rerank", "deadline") == before + 1
    assert world.calls("answer") == 1 and ctx.generation.not_found is False


async def test_exceeded_rewrite_budget_retrieves_with_the_original_question(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "feature_enable_query_rewriting", True)
    monkeypatch.setattr(settings, "chat_stage_budget_rewrite_ms", 30)
    world = await _world(db_session, monkeypatch, {"rewrite": SLOW})

    ctx = await run_pipeline(db_session, world.principal)

    assert _records(ctx) == [("rewrite", "budget", "original_question")]
    assert ctx.config.query_rewrite_result is None
    assert ctx.retrieval.retrieval_queries == [ctx.request.payload.question]
    assert ctx.generation.not_found is False


async def test_exceeded_conflict_budget_skips_detection(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "feature_enable_conflict_detection", True)
    monkeypatch.setattr(settings, "chat_stage_budget_conflict_ms", 30)
    world = await _world(db_session, monkeypatch, {"conflict": SLOW}, two_docs=True)

    ctx = await run_pipeline(db_session, world.principal)

    assert _records(ctx) == [("conflict", "budget", "skipped")]
    assert ctx.retrieval.conflict_detection_applied is False
    assert ctx.generation.not_found is False


async def test_exceeded_tree_search_budget_falls_back_to_one_generation(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "feature_enable_planner_critic_refiner", True)
    monkeypatch.setattr(settings, "feature_enable_tree_search_reasoning", True)
    monkeypatch.setattr(settings, "chat_stage_budget_tree_search_ms", 30)
    world = await _world(db_session, monkeypatch, {"tree_search": SLOW}, two_docs=True)

    ctx = await run_pipeline(db_session, world.principal, question=HIGH_RISK_QUESTION)

    assert ("tree_search", "budget", "single_generation") in _records(ctx)
    assert ctx.generation.llm_call_ran is True and world.calls("answer") == 1


async def test_exceeded_refine_budget_keeps_the_draft(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "feature_enable_planner_critic_refiner", True)
    monkeypatch.setattr(settings, "feature_enable_grounded_answer_verification", True)
    monkeypatch.setattr(settings, "chat_stage_budget_refine_ms", 30)
    # The standard verifier reports an unsupported claim, so the critic asks the refiner.
    world = await _world(
        db_session,
        monkeypatch,
        {"refiner": SLOW},
        two_docs=True,
        responders={"answer": _answer_with_extra_claim, "verifier": _verifier_partial},
    )

    ctx = await run_pipeline(db_session, world.principal, question=HIGH_RISK_QUESTION)

    assert ("refine", "budget", "skipped") in _records(ctx)
    assert ctx.verification.refiner_result is None
    assert ctx.generation.answer.strip()


async def test_exceeded_graph_budget_retrieves_vector_only(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_stage_budget_graph_ms", 30)
    world = await _world(db_session, monkeypatch, {})

    async def graph_on(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def slow_expand(**_kwargs: Any) -> GraphRetrievalResult:
        await asyncio.sleep(SLOW)
        return GraphRetrievalResult(graph_context_enabled=True)

    monkeypatch.setattr(retrieve, "_resolve_graph_rag_enabled", graph_on)
    monkeypatch.setattr(default_deps.graph_retrieval_service, "expand", slow_expand)

    ctx = await run_pipeline(db_session, world.principal)

    assert _records(ctx) == [("graph", "budget", "vector_only")]
    assert ctx.retrieval.graph_context_result.graph_context_used is False
    assert ctx.generation.not_found is False


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


async def _strict_policy(db_session: AsyncSession, world: B2World) -> None:
    repo = AiResponsePolicyRepository()
    policy = await repo.create(
        db_session,
        organization_id=world.organization.id,
        policy_name="Strict",
        grounded_verification_mode="strict",
        grounded_verification_threshold=0.8,
    )
    await repo.activate(db_session, organization_id=world.organization.id, policy=policy)
    await db_session.commit()


async def test_strict_verification_is_never_skipped_the_answer_is_withheld(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "chat_stage_budget_verify_ms", 30)
    world = await _world(db_session, monkeypatch, {"verifier": SLOW})
    await _strict_policy(db_session, world)

    ctx = await run_pipeline(db_session, world.principal)

    assert _records(ctx) == [("verify", "budget", "answer_withheld")]
    assert ctx.generation.not_found is True
    assert ctx.verification.verification_failed is True
    assert ctx.generation.answer == NOT_FOUND_ANSWER
    assert ctx.persist.assistant_message is not None
    assert ctx.persist.assistant_message.content == NOT_FOUND_ANSWER


async def test_standard_verification_budget_skips_the_verifier(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "feature_enable_grounded_answer_verification", True)
    monkeypatch.setattr(settings, "chat_stage_budget_verify_ms", 30)
    world = await _world(db_session, monkeypatch, {"verifier": SLOW})

    ctx = await run_pipeline(db_session, world.principal)

    assert _records(ctx) == [("verify", "budget", "skipped")]
    assert ctx.verification.grounded_verifier_result is None
    assert ctx.generation.not_found is False


# ---------------------------------------------------------------------------
# Policy helpers and the runner hook
# ---------------------------------------------------------------------------


async def test_budget_errors_propagate_untouched_without_a_budget(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _world(db_session, monkeypatch, {})
    ctx = await run_pipeline(db_session, world.principal)

    async def failing() -> int:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await run_with_budget(ctx, "rerank", failing)

    monkeypatch.setattr(settings, "chat_stage_budget_rerank_ms", 1000)

    async def quick() -> int:
        return 7

    outcome = await run_with_budget(ctx, "rerank", quick)
    assert outcome.completed and outcome.value == 7
    budget = stage_budget(ctx, "rerank")
    assert budget is not None and budget.reason == "budget" and budget.seconds == 1.0
    assert stage_budget(ctx, "generate") is None


async def test_runner_timeouts_are_recorded_as_trust_degradations(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _world(db_session, monkeypatch, {})
    ctx = await run_pipeline(db_session, world.principal)
    ctx.stage_degradations.clear()
    ctx.degradations.clear()

    class _Slow:
        name = "rewrite"
        runs_when_terminal = True
        optional = True

        async def run(self, _ctx: ChatContext) -> None:
            await asyncio.sleep(SLOW)

    runner = StageRunner(
        [_Slow()], timeouts={"rewrite": 0.01}, degradation_hook=policies.record_runner_degradation
    )
    await runner.run(ctx)

    assert ctx.degradations == [{"stage": "rewrite", "reason": "timeout"}]
    assert ctx.stage_degradations == [
        StageDegradationRecord(stage="rewrite", reason="budget", action="original_question")
    ]
    ctx.stage_degradations.clear()
    policies.record_runner_degradation(ctx, "persist", "deadline")
    assert _records(ctx) == [("persist", "deadline", "skipped")]
