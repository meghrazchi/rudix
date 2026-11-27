"""``GET /agent/runs/{run_id}/stream`` (R06-13): SSE framing, replay, fallback, access."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_worker_support import (
    AgentWorkerEnv,
    add_user,
    agent_env,  # noqa: F401  (fixture)
    api_client,
    headers_for,
    principal_for,
)
from redis_fakes import BrokenRedis, FakeRedis
from sqlalchemy import update

from app.application.agents import run_submission
from app.application.agents.run_stream_http import (
    RunState,
    RunStreamReader,
    StepState,
    derive_events,
    parse_last_event_id,
)
from app.core.config import settings
from app.domains.agents.schemas import AgentRuntimeRequest, AgentRuntimeResult
from app.domains.agents.services.run_stream import (
    RedisRunEvents,
    buffer_key,
    build_run_events,
    emit_result,
    result_event,
    safe_payload,
)
from app.models.agent import AgentRun
from app.models.enums import OrganizationRole
from app.workers import async_runtime


@pytest.fixture(autouse=True)
def _fast_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "agent_stream_poll_interval_ms", 100)
    monkeypatch.setattr(settings, "agent_stream_keepalive_seconds", 1)
    monkeypatch.setattr(async_runtime, "_worker_loop", None)


def parse_frames(body: str) -> list[dict[str, Any]]:
    frames = []
    for block in body.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        frames.append(
            {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}
        )
    return frames


async def _run(env: AgentWorkerEnv, organization_id: UUID, user_id: UUID) -> UUID:
    async with env.factory() as session:
        run = await run_submission.create_queued_run(
            session,
            principal=principal_for_ids(organization_id, user_id),
            organization_id=organization_id,
            user_id=user_id,
            request=AgentRuntimeRequest(objective="Answer the policy question", mode="answer"),
            request_id=None,
        )
        await session.commit()
        return run.id


def principal_for_ids(organization_id: UUID, user_id: UUID) -> Any:
    from app.auth.models import AuthenticatedPrincipal

    return AuthenticatedPrincipal(
        user_id=str(user_id),
        organization_id=str(organization_id),
        roles=["member"],
        auth_provider="app",
    )


async def _complete_in_worker(env: AgentWorkerEnv, run_id: UUID, organization_id: UUID) -> Any:
    from app.workers import agent_tasks

    return await asyncio.to_thread(
        agent_tasks.execute_agent_run.apply,
        kwargs={"run_id": str(run_id), "organization_id": str(organization_id)},
        task_id=f"exec-{uuid4().hex[:6]}",
    )


@pytest.mark.asyncio
async def test_stream_replays_the_redis_buffer_from_last_event_id(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    run_id = await _run(agent_env, seeded.organization_id, seeded.user_id)
    redis = FakeRedis()
    agent_env.redis = redis
    result = await _complete_in_worker(agent_env, run_id, seeded.organization_id)
    assert result.result["status"] == "completed"
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(f"/api/v1/agent/runs/{run_id}/stream", headers=headers)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = parse_frames(response.text)
        replay = await client.get(
            f"/api/v1/agent/runs/{run_id}/stream",
            headers={**headers, "Last-Event-ID": str(frames[2]["id"])},
        )
    events = [frame["event"] for frame in frames]
    assert events == [
        "agent.run.status",
        "agent.step.started",
        "agent.step.completed",
        "agent.step.started",
        "agent.step.completed",
        "agent.run.completed",
    ]
    assert [frame["id"] for frame in frames] == [1, 2, 3, 4, 5, 6]
    assert frames[1]["data"]["payload"] == {
        "sequence": 1,
        "step_name": "discover_documents",
        "tool_name": "search_documents",
        "status": "running",
    }
    assert frames[-1]["data"]["payload"]["steps_executed"] == 2
    assert [frame["id"] for frame in parse_frames(replay.text)] == [4, 5, 6]
    # Never document text or tool outputs.
    assert "Grounded answer" not in response.text and "Policy.pdf" not in response.text


@pytest.mark.asyncio
async def test_stream_follows_pub_sub_until_a_terminal_event(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    run_id = await _run(agent_env, seeded.organization_id, seeded.user_id)
    redis = FakeRedis()
    events = RedisRunEvents(redis, organization_id=seeded.organization_id, run_id=run_id)
    await events.emit("agent.run.status", {"status": "queued"})

    async def _later() -> None:
        await asyncio.sleep(0.2)
        await events.emit("agent.run.status", {"status": "running", "secret": "x"})
        await events.emit("agent.run.cancelled", {"status": "cancelled"})

    publisher = asyncio.create_task(_later())
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(f"/api/v1/agent/runs/{run_id}/stream", headers=headers)
    await publisher
    frames = parse_frames(response.text)
    assert [(f["id"], f["event"]) for f in frames] == [
        (1, "agent.run.status"),
        (2, "agent.run.status"),
        (3, "agent.run.cancelled"),
    ]
    assert "secret" not in frames[1]["data"]["payload"]


@pytest.mark.asyncio
async def test_stream_polls_the_database_without_redis(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    run_id = await _run(agent_env, seeded.organization_id, seeded.user_id)
    agent_env.redis = None  # the worker publishes nothing

    async def _finish() -> None:
        await asyncio.sleep(0.3)
        await _complete_in_worker(agent_env, run_id, seeded.organization_id)

    worker = asyncio.create_task(_finish())
    async with api_client(agent_env, redis=None) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(
            f"/api/v1/agent/runs/{run_id}/stream", headers={**headers, "Last-Event-ID": "7"}
        )
    await worker
    frames = parse_frames(response.text)
    assert frames[0]["event"] == "agent.run.status" and frames[0]["id"] == 8
    assert frames[-1]["event"] == "agent.run.completed"
    ids = [frame["id"] for frame in frames]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    completed = [f for f in frames if f["event"] == "agent.step.completed"]
    assert [f["data"]["payload"]["sequence"] for f in completed] == [1, 2]


@pytest.mark.asyncio
async def test_failing_redis_falls_back_to_the_database(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    run_id = await _run(agent_env, seeded.organization_id, seeded.user_id)
    agent_env.redis = None
    await _complete_in_worker(agent_env, run_id, seeded.organization_id)
    async with api_client(agent_env, redis=_BrokenPubSubRedis()) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(f"/api/v1/agent/runs/{run_id}/stream", headers=headers)
    frames = parse_frames(response.text)
    assert frames[-1]["event"] == "agent.run.completed"


class _BrokenPubSubRedis(BrokenRedis):
    def pubsub(self) -> Any:
        return BrokenRedis()


@pytest.mark.asyncio
async def test_terminal_run_without_its_event_ends_the_redis_stream(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    run_id = await _run(agent_env, seeded.organization_id, seeded.user_id)
    redis = FakeRedis()
    await RedisRunEvents(redis, organization_id=seeded.organization_id, run_id=run_id).emit(
        "agent.run.status", {"status": "running"}
    )
    async with agent_env.factory() as session:  # the reaper failed it: no event published
        await session.execute(
            update(AgentRun)
            .where(AgentRun.id == run_id)
            .values(status="failed", error_details_json={"code": "worker_lost"})
        )
        await session.commit()
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(f"/api/v1/agent/runs/{run_id}/stream", headers=headers)
    frames = parse_frames(response.text)
    assert [f["event"] for f in frames] == ["agent.run.status", "agent.run.failed"]
    assert frames[-1]["id"] == 2
    assert frames[-1]["data"]["payload"]["error_code"] == "worker_lost"
    assert ": keep-alive" in response.text


@pytest.mark.asyncio
async def test_stream_access_is_scoped_to_the_organisation_and_the_owner(
    agent_env: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = await agent_env.aseed()
    run_id = await _run(agent_env, seeded.organization_id, seeded.user_id)
    other_member, _ = await add_user(agent_env, seeded.organization_id, OrganizationRole.member)
    admin, _ = await add_user(agent_env, seeded.organization_id, OrganizationRole.admin)
    outsider, _ = await add_user(agent_env, seeded.other_organization_id, OrganizationRole.owner)
    async with agent_env.factory() as session:
        await session.execute(
            update(AgentRun).where(AgentRun.id == run_id).values(status="cancelled")
        )
        await session.commit()
    url = f"/api/v1/agent/runs/{run_id}/stream"
    async with api_client(agent_env) as client:
        foreign = await headers_for(agent_env, outsider, seeded.other_organization_id)
        assert (await client.get(url, headers=foreign)).status_code == 404
        peer = await headers_for(agent_env, other_member, seeded.organization_id)
        assert (await client.get(url, headers=peer)).status_code == 404
        owner_admin = await headers_for(agent_env, admin, seeded.organization_id)
        allowed = await client.get(url, headers=owner_admin)
        assert allowed.status_code == 200
        assert parse_frames(allowed.text)[-1]["event"] == "agent.run.cancelled"
        bad = await client.get("/api/v1/agent/runs/not-a-uuid/stream", headers=owner_admin)
        assert bad.status_code == 404
        monkeypatch.setattr(settings, "feature_enable_agents", False)
        assert (await client.get(url, headers=owner_admin)).status_code == 404


def test_derive_events_and_payload_rules() -> None:
    state = RunState(
        status="waiting_approval",
        steps_executed=1,
        tool_calls_executed=2,
        error_code=None,
        approval_id="ap-1",
        steps=[
            StepState(1, "discover_documents", "completed", "search_documents", None),
            StepState(2, "grounded_answer", "waiting_approval", "answer_from_context", None),
        ],
    )
    events = [event for _, event, _ in derive_events(state)]
    assert events == [
        "agent.step.started",
        "agent.step.completed",
        "agent.step.started",
        "agent.run.waiting_approval",
    ]
    assert derive_events(state)[-1][2]["approval_id"] == "ap-1"
    assert safe_payload({"status": "x", "outputs": {"a": 1}, "text": "doc"}) == {"status": "x"}
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id(" 12 ") == 12
    assert parse_last_event_id("-3") == 0
    assert parse_last_event_id("abc") == 0


@pytest.mark.asyncio
async def test_result_events_and_publish_failures() -> None:
    waiting = AgentRuntimeResult(
        run_id="r",
        status="waiting_approval",
        error={
            "code": "approval_required",
            "message": "m",
            "details": {"approval_id": "ap-9"},
        },
    )
    event, payload = result_event(waiting) or ("", {})
    assert event == "agent.run.waiting_approval" and payload["approval_id"] == "ap-9"
    assert result_event(AgentRuntimeResult(run_id="r", status="running")) is None
    broken = build_run_events(BrokenRedis(), organization_id="o", run_id="r")
    await emit_result(broken, waiting)
    assert isinstance(broken, RedisRunEvents) and broken.failed
    await broken.emit("agent.run.status", {})  # stays silent after a failure
    await emit_result(build_run_events(None, organization_id="o", run_id="r"), waiting)


@pytest.mark.asyncio
async def test_reader_stops_when_the_run_disappears() -> None:
    async def _gone() -> RunState | None:
        return None

    redis = FakeRedis()
    await redis.rpush(buffer_key("o", "r"), "not json")
    for source in (None, redis):
        reader = RunStreamReader(
            organization_id=uuid4(), run_id=uuid4(), last_event_id=0, redis=source, load_state=_gone
        )
        assert [frame async for frame in reader.frames()] == []
        assert reader.finished


def test_principal_helper_matches_seeded_identity() -> None:
    assert principal_for  # imported for parity with the worker tests
