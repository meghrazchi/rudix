"""Resume buffer internals (R05-13): the entry cap and delta coalescing, replay edge cases,
the attached marker, drop helpers, and the append script against a real Redis."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from chat_resume_support import DroppableSocket
from chat_stream_support import (
    RecordingSocket,
    StreamingRecordingProvider,
    make_world,
    principal_for,
)
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import chat_query_client  # noqa: F401  (pytest fixture re-export)

from app.application.chat.transports import resume_buffer
from app.application.chat.transports.resume_buffer import (
    BufferingEmitter,
    ResumeBuffer,
    coalesce,
    replay_buffer,
    resume_key,
    trim_entry,
)
from app.application.chat.transports.ws import WsSequence
from app.application.chat.transports.ws_resume import run_ws_resume
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.interfaces.http import chat as chat_api
from tests.redis_fakes import BrokenRedis, FakeClock, FakeRedis

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("chat_query_client")]


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis(clock=FakeClock(1_000_000_000))
    monkeypatch.setattr(redis_module, "redis_client", fake)
    return fake


# -- buffer cap and coalescing -------------------------------------------------------------


async def test_deltas_beyond_the_cap_are_coalesced_and_trimmed_for_the_reader(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    from app.application.chat.pipeline.context import RunIds
    from app.application.chat.pipeline.events import ChatEvent

    monkeypatch.setattr(settings, "chat_resume_buffer_max_events", 3)
    key = resume_key(uuid4(), uuid4(), uuid4())
    emitter = BufferingEmitter(
        RecordingSocket(),
        buffer=ResumeBuffer(fake_redis, key),
        request_id="r",
        ids=RunIds(),
        sequence=WsSequence(),
    )
    await emitter.emit(ChatEvent(type="generation.started", payload={"mode": "live"}))
    for piece in ("ab", "cd", "ef", "gh", "ij"):
        await emitter.emit(ChatEvent(type="generation.delta", payload={"text": piece}))
    await emitter.emit(ChatEvent(type="chat.completed", payload={}))
    stored = [json.loads(v) for v in fake_redis.keyspace.lists[key]]
    assert [e["event"] for e in stored] == [
        "generation.started",
        "generation.delta",
        "generation.delta",
        "chat.completed",
    ]
    assert stored[2]["payload"]["text"] == "cdefghij"
    assert stored[2]["coalesced"] == [[3, 2], [4, 2], [5, 2], [6, 2]]

    for last, expected in ((0, "abcdefghij"), (2, "cdefghij"), (4, "ghij"), (5, "ij")):
        sent: list[dict[str, Any]] = []

        async def send_text(data: str, sink: list[dict[str, Any]] = sent) -> None:
            sink.append(json.loads(data))

        async def on_resumed(_count: int) -> None:
            return None

        result = await replay_buffer(
            fake_redis,
            key,
            last_stream_sequence=last,
            sequence=WsSequence(),
            send_text=send_text,
            on_resumed=on_resumed,
        )
        assert result.terminal == "chat.completed"
        text = "".join(e["payload"]["text"] for e in sent if e["event"] == "generation.delta")
        assert text == expected
        assert all("coalesced" not in e for e in sent)

    assert trim_entry({"stream_sequence": 2, "payload": {"text": "x"}}, 2) is None
    merged = coalesce(
        {"stream_sequence": 1, "payload": {"text": "a"}},
        {"stream_sequence": 2, "payload": {"text": "b"}},
    )
    assert merged["payload"]["text"] == "ab" and merged["stream_sequence"] == 2


async def test_request_cancel_and_read_flag_tolerate_a_failing_redis() -> None:
    broken = BrokenRedis()
    await resume_buffer.request_cancel(broken, "k")
    assert await resume_buffer.read_flag(broken, "k") is False


# -- live Redis (CI lane) -------------------------------------------------------------------


@pytest_asyncio.fixture
async def live_redis() -> AsyncIterator[Any]:
    from redis.asyncio import Redis

    url = os.environ.get("TEST_REDIS_URL", "").strip()
    if not url:
        pytest.skip("TEST_REDIS_URL is not set; skipping live Redis script tests")
    client: Any = Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Redis not reachable at TEST_REDIS_URL; skipping live script tests")
    try:
        yield client
    finally:
        await client.aclose()


@pytest.mark.requires_redis
async def test_append_script_matches_reference(live_redis: Any) -> None:
    fake = FakeRedis()
    key = f"rudix:test:chat:resume:v1:{uuid4()}"
    try:
        for mode, value in (("push", "a"), ("set", "b"), ("push", "c"), ("set", "d")):
            for client in (live_redis, fake):
                script = resume_buffer.get_script(client, resume_buffer.APPEND_SCRIPT)
                length = await script(keys=[key], args=[mode, value, 60_000])
                assert int(length) == (1 if value in "ab" else 2)
        assert await live_redis.lrange(key, 0, -1) == await fake.lrange(key, 0, -1) == ["b", "d"]
        assert 0 < await live_redis.pttl(key) <= 60_000
    finally:
        await live_redis.delete(key)


# -- edge cases -----------------------------------------------------------------------------


async def _collect_replay(
    fake: FakeRedis, key: str, last: int = 0
) -> tuple[resume_buffer.ReplayResult, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []

    async def send_text(data: str) -> None:
        sent.append(json.loads(data))

    async def on_resumed(_count: int) -> None:
        return None

    result = await replay_buffer(
        fake,
        key,
        last_stream_sequence=last,
        sequence=WsSequence(),
        send_text=send_text,
        on_resumed=on_resumed,
    )
    return result, sent


def _entry(event: str, seq: int) -> str:
    return json.dumps({"event": event, "stream_sequence": seq})


async def test_replay_skips_unreadable_entries_and_stops_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    key = resume_key(uuid4(), uuid4(), uuid4())
    for raw in ("not json", "[1, 2]", _entry("chat.completed", 1)):
        fake_redis.keyspace.rpush(key, raw)
    result, sent = await _collect_replay(fake_redis, key)
    assert result.terminal == "chat.completed"
    assert [e["event"] for e in sent] == ["chat.completed"]

    open_key = resume_key(uuid4(), uuid4(), uuid4())
    fake_redis.keyspace.rpush(open_key, _entry("generation.delta", 1))
    monkeypatch.setattr(settings, "chat_resume_buffer_ttl_seconds", 0)
    result, _ = await _collect_replay(fake_redis, open_key)
    assert result.expired is True and result.terminal is None
    assert resume_buffer._decode(b'{"a": 1}') == {"a": 1}


async def test_tailing_reader_refreshes_its_attached_marker(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    monkeypatch.setattr(resume_buffer, "_ATTACHED_REFRESH_SECONDS", 0.0)
    monkeypatch.setattr(settings, "chat_resume_poll_ms", 10)
    key = resume_key(uuid4(), uuid4(), uuid4())
    fake_redis.keyspace.rpush(key, _entry("generation.delta", 1))
    task = asyncio.create_task(_collect_replay(fake_redis, key))
    await asyncio.sleep(0.05)
    sets_before = fake_redis.commands.count("SET")
    await asyncio.sleep(0.05)
    assert fake_redis.commands.count("SET") > sets_before
    fake_redis.keyspace.rpush(key, _entry("chat.error", 2))
    result, _sent = await asyncio.wait_for(task, timeout=5)
    assert result.terminal == "chat.error"


async def test_drop_handling_and_cancel_helpers() -> None:
    from app.application.chat.transports import ws as ws_transport

    async def forever() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(forever())
    ws_transport.handle_ws_drop(task, None)  # no handle: cancel at once
    with pytest.raises(asyncio.CancelledError):
        await task

    class _FailingEmitter:
        async def buffer_cancelled(self) -> None:
            raise ConnectionError("redis went away")

    await ws_transport._buffer_cancelled(_FailingEmitter())  # type: ignore[arg-type]
    await ws_transport._buffer_cancelled(object())  # type: ignore[arg-type]


async def test_resume_tolerates_a_closed_socket(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    principal = principal_for(world)
    message_id = uuid4()
    key = resume_key(principal.organization_id, principal.user_id, message_id)
    fake_redis.keyspace.rpush(key, _entry("chat.completed", 1))
    closed = DroppableSocket()
    closed.drop()
    await run_ws_resume(
        websocket=closed,
        payload={"message_id": str(message_id), "last_stream_sequence": 0},
        principal=principal,
        sequence=WsSequence(),
        session_factory=chat_api.SessionLocal,
    )
    assert closed.events == []
