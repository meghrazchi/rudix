"""Stage runner, events, session scope, and errors of the chat pipeline (R05-01)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from app.application.chat.pipeline.context import ChatContext, RequestState
from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.events import (
    ActivityStepEmitter,
    ChatEvent,
    CollectingEmitter,
    plural,
)
from app.application.chat.pipeline.pipeline import ChatPipeline, default_stages
from app.application.chat.pipeline.runner import (
    ChatStageTimeoutError,
    StageRunner,
    record_degradation,
)
from app.application.chat.pipeline.sessions import SingleSessionScope
from app.auth.models import AuthenticatedPrincipal
from app.core.metrics import CHAT_STAGE_SECONDS
from app.domains.chat.schemas.chat import ChatQueryRequest


def _context(emitter: CollectingEmitter | None = None) -> ChatContext:
    emitter = emitter or CollectingEmitter()
    return ChatContext(
        request=RequestState(
            payload=ChatQueryRequest(question="How much leave?"),
            principal=AuthenticatedPrincipal(
                user_id=str(uuid4()),
                organization_id=str(uuid4()),
                roles=["member"],
                auth_provider="app",
            ),
            transport="http",
            request_id="runner-test",
            user_id=uuid4(),
            organization_id=uuid4(),
            user_roles=["member"],
        ),
        deps=default_deps,
        emitter=emitter,
        sessions=SingleSessionScope(object()),  # type: ignore[arg-type]
        steps=ActivityStepEmitter(emitter),
    )


class _Stage:
    def __init__(
        self,
        name: str,
        calls: list[str],
        *,
        runs_when_terminal: bool = True,
        optional: bool = False,
        sleep: float = 0.0,
        terminal: bool = False,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.runs_when_terminal = runs_when_terminal
        self.optional = optional
        self._calls = calls
        self._sleep = sleep
        self._terminal = terminal
        self._error = error

    async def run(self, ctx: ChatContext) -> None:
        self._calls.append(self.name)
        if self._sleep:
            await asyncio.sleep(self._sleep)
        if self._terminal:
            ctx.terminal = True
        if self._error is not None:
            raise self._error


def _histogram_count(stage: str) -> float:
    for metric in CHAT_STAGE_SECONDS.collect():
        for sample in metric.samples:
            if sample.name.endswith("_count") and sample.labels.get("stage") == stage:
                return sample.value
    return 0.0


async def test_runner_runs_stages_in_order_and_observes_each() -> None:
    calls: list[str] = []
    before = _histogram_count("runner_order_a")
    runner = StageRunner([_Stage("runner_order_a", calls), _Stage("runner_order_b", calls)])
    ctx = _context()
    assert await runner.run(ctx) is ctx
    assert calls == ["runner_order_a", "runner_order_b"]
    assert _histogram_count("runner_order_a") == before + 1
    assert [stage.name for stage in runner.stages] == calls


async def test_terminal_skips_stages_that_do_not_run_when_terminal() -> None:
    calls: list[str] = []
    runner = StageRunner(
        [
            _Stage("direct", calls, terminal=True),
            _Stage("retrieve", calls, runs_when_terminal=False),
            _Stage("persist", calls),
        ]
    )
    ctx = await runner.run(_context())
    assert ctx.terminal is True
    assert calls == ["direct", "persist"]


async def test_stage_timeout_records_degradation_and_fails_required_stage() -> None:
    calls: list[str] = []
    runner = StageRunner([_Stage("slow", calls, sleep=0.2)], timeouts={"slow": 0.01})
    ctx = _context()
    with pytest.raises(ChatStageTimeoutError) as excinfo:
        await runner.run(ctx)
    assert excinfo.value.stage == "slow"
    assert ctx.degradations == [{"stage": "slow", "reason": "timeout"}]


async def test_optional_stage_timeout_is_skipped() -> None:
    calls: list[str] = []
    seen: list[tuple[str, str]] = []
    runner = StageRunner(
        [_Stage("optional", calls, sleep=0.2, optional=True), _Stage("after", calls)],
        timeouts={"optional": 0.01},
        degradation_hook=lambda ctx, stage, reason: seen.append((stage, reason)),
    )
    await runner.run(_context())
    assert calls == ["optional", "after"]
    assert seen == [("optional", "timeout")]


async def test_expired_deadline_skips_optional_stage_without_running_it() -> None:
    calls: list[str] = []
    runner = StageRunner(
        [_Stage("shortcut", calls, optional=True), _Stage("persist", calls)],
        clock=lambda: 100.0,
    )
    ctx = _context()
    ctx.deadline = 50.0
    with pytest.raises(ChatStageTimeoutError):
        await runner.run(ctx)
    assert calls == []
    assert ctx.degradations == [
        {"stage": "shortcut", "reason": "deadline"},
        {"stage": "persist", "reason": "deadline"},
    ]


async def test_deadline_caps_the_stage_timeout() -> None:
    calls: list[str] = []
    runner = StageRunner(
        [_Stage("generate", calls, sleep=0.2)],
        timeouts={"generate": 5.0},
        clock=lambda: 0.0,
    )
    ctx = _context()
    ctx.deadline = 0.01
    with pytest.raises(ChatStageTimeoutError):
        await runner.run(ctx)
    assert ctx.degradations == [{"stage": "generate", "reason": "deadline"}]


async def test_stage_errors_propagate_untouched_without_a_budget() -> None:
    calls: list[str] = []
    error = TimeoutError("provider timeout inside the stage")
    runner = StageRunner([_Stage("generate", calls, error=error)])
    ctx = _context()
    with pytest.raises(TimeoutError) as excinfo:
        await runner.run(ctx)
    assert excinfo.value is error
    assert ctx.degradations == []


async def test_background_tasks_are_cancelled_when_the_run_ends() -> None:
    started = asyncio.Event()
    tasks_seen: list[asyncio.Task[Any]] = []

    async def _forever() -> None:
        started.set()
        await asyncio.sleep(3600)

    class _Spawner:
        name = "spawn"
        runs_when_terminal = True
        optional = False

        async def run(self, ctx: ChatContext) -> None:
            pending = asyncio.create_task(_forever())
            done = asyncio.create_task(asyncio.sleep(0))
            await done
            tasks_seen.extend([pending, done])
            ctx.background_tasks.extend([pending, done])
            await started.wait()
            raise ChatPipelineError(code="boom", status_code=500, message="Boom")

    ctx = _context()
    with pytest.raises(ChatPipelineError):
        await StageRunner([_Spawner()]).run(ctx)
    assert tasks_seen[0].cancelled()
    assert tasks_seen[1].done() and not tasks_seen[1].cancelled()
    assert ctx.background_tasks == []


def test_record_degradation_keeps_stage_and_reason() -> None:
    ctx = _context()
    record_degradation(ctx, "rerank_pack", "timeout")
    assert ctx.degradations == [{"stage": "rerank_pack", "reason": "timeout"}]


async def test_emit_step_builds_the_activity_payload_and_sequence() -> None:
    emitter = CollectingEmitter()
    ctx = _context(emitter)
    await ctx.emit_step("checking_sources", "Checking accessible sources", "running")
    await ctx.emit_step("checking_sources", "Checking accessible sources", "success", "Done", 5)
    await ctx.emit_step("drafting_answer", "Drafting answer", "pending")
    await ctx.emit(ChatEvent(type="retrieval.started"))
    payloads = [event.payload for event in emitter.events[:3]]
    assert payloads == [
        {
            "step_key": "checking_sources",
            "sequence": 1,
            "label": "Checking accessible sources",
            "state": "running",
            "detail": None,
            "duration_ms": None,
        },
        {
            "step_key": "checking_sources",
            "sequence": 1,
            "label": "Checking accessible sources",
            "state": "success",
            "detail": "Done",
            "duration_ms": 5,
        },
        {
            "step_key": "drafting_answer",
            "sequence": 2,
            "label": "Drafting answer",
            "state": "pending",
            "detail": None,
            "duration_ms": None,
        },
    ]
    assert {event.type for event in emitter.events} == {"activity.step.update", "retrieval.started"}
    assert ctx.job_id == ""


def test_plural() -> None:
    assert plural(1, "source") == "1 source"
    assert plural(2, "source") == "2 sources"


async def test_single_session_scope_yields_the_request_session_for_every_phase() -> None:
    session = object()
    scope = SingleSessionScope(session)  # type: ignore[arg-type]
    assert scope.session is session
    for phase in (scope.read, scope.short, scope.write):
        async with phase() as yielded:
            assert yielded is session


def test_pipeline_error_maps_to_the_safe_http_error() -> None:
    error = ChatPipelineError(code="retrieval_failed", status_code=503, message="Unavailable")
    http_error = error.to_http_exception()
    assert http_error.status_code == 503
    assert http_error.detail == {"code": "retrieval_failed", "message": "Unavailable"}
    assert error.payload is None


def test_default_stages_keep_the_query_chat_order() -> None:
    assert [stage.name for stage in default_stages()] == [
        "authorize",
        "guard",
        "resolve_config",
        "shortcut",
        "rewrite",
        "direct_answers",
        "retrieve",
        "rerank_pack",
        "generate",
        "verify",
        "persist",
    ]


async def test_pipeline_runs_custom_stages_with_a_built_context() -> None:
    calls: list[str] = []
    principal = AuthenticatedPrincipal(
        user_id=str(uuid4()), organization_id=str(uuid4()), roles=["member"], auth_provider="app"
    )
    emitter = CollectingEmitter()
    ctx = await ChatPipeline(default_deps, stages=[_Stage("only", calls)]).run(
        ChatQueryRequest(question="Q?"),
        principal,
        "http",
        emitter,
        SingleSessionScope(object()),  # type: ignore[arg-type]
        "req-1",
    )
    assert calls == ["only"]
    assert str(ctx.request.organization_id) == principal.organization_id
    assert ctx.request.user_roles == ["member"]
    assert ctx.emitter is emitter
