"""Unit tests of the R05-03 stream helpers: final event, replace reason, guards."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.application.chat.pipeline.events import ChatEvent
from app.application.chat.pipeline.stages import _final, _llm
from app.application.chat.pipeline.stream_state import StreamState
from app.domains.ai_response_policy.services.policy_engine import (
    EffectivePolicy,
    PolicyEvaluationResult,
)

pytestmark = [pytest.mark.asyncio]


def _ctx(*, answer: str = "Final.", transport: str = "ws") -> Any:
    events: list[ChatEvent] = []
    steps: list[tuple[str, str]] = []

    async def emit(event: ChatEvent) -> None:
        events.append(event)

    async def emit_step(key: str, label: str, state: str, *args: Any) -> None:
        steps.append((key, state))

    return SimpleNamespace(
        events=events,
        steps=steps,
        emit=emit,
        emit_step=emit_step,
        request=SimpleNamespace(transport=transport),
        ids=SimpleNamespace(assistant_message_id=uuid4()),
        stream=StreamState(),
        generation=SimpleNamespace(
            answer=answer, not_found=False, citations=[], drafting_started=False
        ),
        verification=SimpleNamespace(
            ai_policy_result=PolicyEvaluationResult(),
            confidence_score=0.5,
            confidence_category="medium",
            citation_validation_failed=False,
        ),
        config=SimpleNamespace(ai_effective_policy=EffectivePolicy(policy_id=None, source="none")),
    )


async def test_start_drafting_runs_once_and_keeps_the_first_mode() -> None:
    ctx = _ctx()
    await _llm.start_drafting(ctx, "buffered")
    await _llm.start_drafting(ctx, "live")  # a tree-search fallback does not restart it
    assert [e.type for e in ctx.events] == ["generation.started"]
    assert ctx.events[0].payload == {"mode": "buffered"} and ctx.stream.mode == "buffered"
    assert ctx.steps == [("drafting_answer", "running")]


async def test_empty_delta_is_not_sent() -> None:
    ctx = _ctx()
    await _llm.emit_delta(ctx, "")
    assert ctx.events == [] and ctx.stream.ttft_observed is False


async def test_final_event_is_sent_once() -> None:
    ctx = _ctx()
    await _final.emit_final_events(ctx)
    await _final.emit_final_events(ctx)
    assert [e.type for e in ctx.events] == ["generation.final"]
    assert ctx.events[0].message_id == str(ctx.ids.assistant_message_id)


async def test_blocked_policy_result_is_the_replace_reason() -> None:
    ctx = _ctx(answer="Refused by policy.")
    ctx.generation.drafting_started = True
    ctx.stream.mode = "live"
    ctx.stream.streamed = ["Model text"]
    ctx.verification.ai_policy_result = PolicyEvaluationResult(blocked=True)
    await _final.emit_final_events(ctx)
    replace = ctx.events[0]
    assert replace.type == "generation.replace"
    assert replace.payload == {"text": "Refused by policy.", "reason": "policy"}
    assert ctx.events[1].type == "generation.final"


def test_disclaimer_counts_as_policy_only_when_a_policy_is_active() -> None:
    ctx = _ctx()
    ctx.verification.ai_policy_result = PolicyEvaluationResult(disclaimer_text="Note.")
    assert _final.replace_reason(ctx) == "normalisation"  # no active policy
    ctx.config.ai_effective_policy = EffectivePolicy(policy_id="p", source="org")
    assert _final.replace_reason(ctx) == "policy"
    ctx.generation.not_found = True
    assert _final.replace_reason(ctx) == "normalisation"
