"""``GET /events/stream`` (R07-07): access, org and audience isolation, replay, limits."""

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
)
from redis_fakes import BrokenRedis, FakeRedis

from app.application.realtime import publisher
from app.application.realtime.stream_http import (
    RealtimeStreamReader,
    acquire_connection_slot,
    parse_last_event_id,
)
from app.core.config import settings
from app.domains.realtime.events import (
    Audience,
    RealtimeEvent,
    buffer_key,
    connection_key,
    document_status_events,
    notification_event,
)
from app.models.enums import OrganizationRole

STREAM = "/api/v1/events/stream"


@pytest.fixture(autouse=True)
def _fast_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "realtime_events_enabled", True)
    monkeypatch.setattr(settings, "realtime_stream_max_seconds", 0.4)
    monkeypatch.setattr(settings, "realtime_stream_keepalive_seconds", 0.15)


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


async def _publish(redis: FakeRedis, events: list[RealtimeEvent] | RealtimeEvent) -> None:
    await publisher.publish_now(events, redis=redis)


def _status_events(organization_id: UUID, uploader_id: UUID | None) -> list[RealtimeEvent]:
    return document_status_events(
        organization_id=organization_id,
        document_id=uuid4(),
        status="indexed",
        uploader_id=uploader_id,
    )


async def test_disabled_answers_404(
    agent_env: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "realtime_events_enabled", False)
    seeded = await agent_env.aseed()
    async with api_client(agent_env, redis=FakeRedis()) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(STREAM, headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "feature_not_available"


async def test_requires_a_token(agent_env: AgentWorkerEnv) -> None:  # noqa: F811
    async with api_client(agent_env, redis=FakeRedis()) as client:
        response = await client.get(STREAM)
        tokenised = await client.get(f"{STREAM}?access_token=abc")
    assert response.status_code == 401
    assert tokenised.status_code == 401  # a token in the URL is never read


@pytest.mark.parametrize("redis", [None, BrokenRedis()], ids=["missing", "unreachable"])
async def test_without_redis_answers_503(
    agent_env: AgentWorkerEnv,  # noqa: F811
    redis: Any,
) -> None:
    seeded = await agent_env.aseed()
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(STREAM, headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "realtime_unavailable"


async def test_member_sees_own_and_hint_events_never_other_org_or_users(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    other_user, _ = await add_user(agent_env, seeded.organization_id, OrganizationRole.member)
    redis = FakeRedis()
    mine = _status_events(seeded.organization_id, seeded.user_id)
    theirs = _status_events(seeded.organization_id, other_user)
    foreign = _status_events(seeded.other_organization_id, seeded.user_id)
    await _publish(redis, [*mine, *theirs, *foreign])
    await _publish(
        redis,
        notification_event(
            organization_id=seeded.organization_id, notification_id=uuid4(), user_id=other_user
        ),
    )
    # An entry for another organisation planted in this organisation's buffer is dropped.
    forged = RealtimeEvent.build(
        "incident",
        organization_id=seeded.other_organization_id,
        payload={"incident_id": "i1", "status": "investigating"},
        audience=Audience.of(all_members=True),
    )
    await redis.rpush(buffer_key(seeded.organization_id), forged.to_entry(99))

    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(STREAM, headers=headers, timeout=10)
        other_headers = await headers_for(agent_env, other_user, seeded.organization_id)
        other = await client.get(STREAM, headers=other_headers, timeout=10)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    frames = parse_frames(response.text)
    assert [(f["event"], f["id"]) for f in frames] == [
        ("document.status", 1),
        ("documents.changed", 2),
        ("documents.changed", 4),
    ]
    assert frames[0]["data"]["payload"] == mine[0].payload
    assert set(frames[0]["data"]) == {"type", "organization_id", "occurred_at", "payload"}
    assert all(f["data"]["organization_id"] == str(seeded.organization_id) for f in frames)
    other_frames = parse_frames(other.text)
    assert [f["event"] for f in other_frames] == [
        "documents.changed",
        "document.status",
        "documents.changed",
        "notification.created",
    ]


async def test_admin_receives_every_document_status(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    admin, _ = await add_user(agent_env, seeded.organization_id, OrganizationRole.admin)
    redis = FakeRedis()
    await _publish(redis, _status_events(seeded.organization_id, seeded.user_id))
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, admin, seeded.organization_id)
        response = await client.get(STREAM, headers=headers, timeout=10)
    assert [f["event"] for f in parse_frames(response.text)] == [
        "document.status",
        "documents.changed",
    ]


async def test_replay_after_last_event_id_and_reset_counter(
    agent_env: AgentWorkerEnv,  # noqa: F811
) -> None:
    seeded = await agent_env.aseed()
    redis = FakeRedis()
    for _ in range(3):
        await _publish(redis, _status_events(seeded.organization_id, seeded.user_id))
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        replay = await client.get(STREAM, headers={**headers, "Last-Event-ID": "4"}, timeout=10)
        # A Last-Event-ID beyond the counter (Redis lost it) replays everything.
        reset = await client.get(STREAM, headers={**headers, "Last-Event-ID": "900"}, timeout=10)
    assert [f["id"] for f in parse_frames(replay.text)] == [5, 6]
    assert len(parse_frames(reset.text)) == 6
    assert parse_last_event_id(" 12 ") == 12
    assert parse_last_event_id("x") == 0
    assert parse_last_event_id(None) == 0


async def test_follows_the_channel_with_keepalives(
    agent_env: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "realtime_stream_max_seconds", 0.8)
    seeded = await agent_env.aseed()
    redis = FakeRedis()

    async def _later() -> None:
        await asyncio.sleep(0.4)
        await _publish(redis, _status_events(seeded.organization_id, seeded.user_id))

    task = asyncio.create_task(_later())
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        response = await client.get(
            STREAM, headers={**headers, "Accept-Encoding": "gzip"}, timeout=10
        )
    await task
    assert ": keep-alive" in response.text
    assert [f["event"] for f in parse_frames(response.text)] == [
        "document.status",
        "documents.changed",
    ]
    # GZip never compresses text/event-stream.
    assert "content-encoding" not in response.headers


async def test_connection_cap_answers_429_and_slots_are_released(
    agent_env: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "realtime_max_connections_per_user", 2)
    seeded = await agent_env.aseed()
    redis = FakeRedis()
    org, user = str(seeded.organization_id), str(seeded.user_id)
    assert await acquire_connection_slot(redis, organization_id=org, user_id=user)
    assert await acquire_connection_slot(redis, organization_id=org, user_id=user)
    async with api_client(agent_env, redis=redis) as client:
        headers = await headers_for(agent_env, seeded.user_id, seeded.organization_id)
        refused = await client.get(STREAM, headers=headers)
        assert refused.status_code == 429
        assert refused.json()["error"]["code"] == "realtime_connection_limit"
        assert redis.keyspace.get(connection_key(org, user)) == "2"
        await redis.decr(connection_key(org, user))
        accepted = await client.get(STREAM, headers=headers, timeout=10)
    assert accepted.status_code == 200
    # The finished stream gave its slot back.
    assert redis.keyspace.get(connection_key(org, user)) == "1"
    assert 0 < redis.keyspace.pttl(connection_key(org, user))


async def test_reader_ends_quietly_when_redis_breaks_mid_stream() -> None:
    reader = RealtimeStreamReader(
        organization_id=str(uuid4()),
        user_id=str(uuid4()),
        roles=["member"],
        last_event_id=0,
        redis=_BrokenAfterSubscribe(),
    )
    frames = [frame async for frame in reader.frames()]
    assert frames == []


class _BrokenAfterSubscribe(FakeRedis):
    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        raise ConnectionError("gone")

    async def decr(self, key: str) -> int:
        raise ConnectionError("gone")


async def test_reader_skips_duplicates_between_replay_and_channel() -> None:
    organization_id, user_id = str(uuid4()), str(uuid4())
    reader = RealtimeStreamReader(
        organization_id=organization_id,
        user_id=user_id,
        roles=["owner"],
        last_event_id=0,
        redis=FakeRedis(),
    )
    event = _status_events(UUID(organization_id), None)[0]
    first = reader.accept(event.to_entry(3))
    assert first is not None and first.startswith("id: 3\nevent: document.status\n")
    assert reader.accept(event.to_entry(3)) is None
    assert reader.accept("garbage") is None
