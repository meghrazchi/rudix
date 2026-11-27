"""Resumable WebSocket chat runs (R05-13, plan contract 4.2.7).

The buffer lives in a ``FakeRedis`` shared by every connection, so a ``chat.resume`` on a
second connection reads only Redis, as a second replica would.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest
from chat_resume_support import (
    DroppableSocket,
    connect,
    install_ws,
    stranger,
    stream_sequences,
    wait_for_watchers,
)
from chat_stream_support import (
    TEXT_A,
    RecordingSocket,
    StreamingRecordingProvider,
    counter_value,
    make_world,
    principal_for,
    run_ws,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import chat_query_client  # noqa: F401  (pytest fixture re-export)

from app.application.chat.transports.resume_buffer import (
    resume_key,
)
from app.application.chat.transports.ws import WsSequence
from app.application.chat.transports.ws_resume import parse_resume_payload, run_ws_resume
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.metrics import (
    CHAT_RESUME_BUFFER_ERRORS_TOTAL,
    CHAT_WS_DROP_TOTAL,
    CHAT_WS_RESUME_TOTAL,
)
from app.interfaces.http import chat as chat_api
from app.models.usage import UsageEvent
from tests.redis_fakes import BrokenRedis, FakeClock, FakeRedis

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("chat_query_client")]


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis(clock=FakeClock(1_000_000_000))
    monkeypatch.setattr(redis_module, "redis_client", fake)
    monkeypatch.setattr(settings, "chat_ws_resume_grace_seconds", 30)
    return fake


async def _world(db: AsyncSession, monkeypatch: pytest.MonkeyPatch, hold: asyncio.Event) -> Any:
    provider = StreamingRecordingProvider(chunk_size=6, hold=hold, hold_at=3)
    return provider, await make_world(db, monkeypatch, provider)


async def _start_and_drop(
    world: Any, socket: DroppableSocket
) -> tuple[asyncio.Task[None], str, int]:
    connection = connect(socket)
    socket.push("chat.start", {"chat_session_id": None, **world.payload})
    await socket.wait_for("generation.delta")
    socket.drop()
    await asyncio.wait_for(connection, timeout=5)
    seen = socket.run_events()
    message_id = next(e["message_id"] for e in seen if e["message_id"])
    return connection, message_id, max(stream_sequences(seen))


async def _usage_types(db: AsyncSession) -> list[str]:
    return [u.event_type for u in (await db.execute(select(UsageEvent))).scalars().all()]


async def test_dropped_stream_resumes_on_another_connection_without_gaps(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    hold = asyncio.Event()
    provider, world = await _world(db_session, monkeypatch, hold)
    principal = principal_for(world)
    install_ws(monkeypatch, [principal, principal])
    replayed_before = counter_value(CHAT_WS_RESUME_TOTAL, outcome="replayed")
    first = DroppableSocket()
    _, message_id, last = await _start_and_drop(world, first)
    assert provider.active_streams == 1  # the run survived the drop (grace window)

    second = DroppableSocket()
    connection = connect(second)
    second.push("chat.resume", {"message_id": message_id, "last_stream_sequence": last})
    await second.wait_for("chat.resumed")
    hold.set()
    await second.wait_for("chat.completed")
    second.drop()
    await asyncio.wait_for(connection, timeout=5)
    await wait_for_watchers()

    resumed = second.of("chat.resumed")[0]
    assert resumed["payload"]["message_id"] == message_id
    assert resumed["stream_sequence"] is None
    combined = stream_sequences(first.run_events()) + stream_sequences(second.run_events())
    assert combined == list(range(1, len(combined) + 1))  # no duplicate, no gap
    assert first.deltas() + second.deltas() == TEXT_A
    completed = second.of("chat.completed")[0]["payload"]["response"]
    assert completed["answer"] == TEXT_A and completed["message_id"] == message_id
    sequences = [e["sequence"] for e in second.events]
    assert sequences == sorted(sequences) and len(set(sequences)) == len(sequences)
    assert counter_value(CHAT_WS_RESUME_TOTAL, outcome="replayed") == replayed_before + 1
    assert await _usage_types(db_session) == ["chat.completion"]


async def test_resume_after_completion_replays_then_rebuilds_from_the_stored_answer(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    socket = RecordingSocket(provider)
    await run_ws(world, socket)
    original = socket.of("chat.completed")[0]
    response = original["payload"]["response"]
    message_id = response["message_id"]
    assert stream_sequences(socket.events) == list(range(1, len(socket.events) + 1))

    principal = principal_for(world)
    replay = RecordingSocket()
    await run_ws_resume(
        websocket=replay,
        payload={"message_id": message_id, "last_stream_sequence": 0},
        principal=principal,
        sequence=WsSequence(),
        session_factory=chat_api.SessionLocal,
    )
    assert replay.events[0]["payload"]["replayed"] == len(socket.events)
    assert [e["event"] for e in replay.events[1:]] == [e["event"] for e in socket.events]

    fake_redis.clock.advance(settings.chat_resume_buffer_ttl_seconds * 1000 + 1)  # type: ignore[attr-defined]
    rebuilt_before = counter_value(CHAT_WS_RESUME_TOTAL, outcome="rebuilt")
    stored = RecordingSocket()
    await run_ws_resume(
        websocket=stored,
        payload={"message_id": message_id, "last_stream_sequence": 5},
        principal=principal,
        sequence=WsSequence(),
        session_factory=chat_api.SessionLocal,
    )
    assert [e["event"] for e in stored.events] == ["chat.resumed", "chat.completed"]
    assert stored.events[0]["payload"] == {"message_id": message_id, "replayed": 0}
    payload = stored.events[1]["payload"]
    assert payload["rebuilt"] is True
    rebuilt = payload["response"]
    assert rebuilt["answer"] == response["answer"] == TEXT_A
    assert rebuilt["chat_session_id"] == response["chat_session_id"]
    assert [c["chunk_id"] for c in rebuilt["citations"]] == [
        c["chunk_id"] for c in response["citations"]
    ]
    assert rebuilt["confidence_category"] == response["confidence_category"]
    assert rebuilt["trust_metadata"] is not None
    assert stored.events[1]["conversation_id"] == response["chat_session_id"]
    assert counter_value(CHAT_WS_RESUME_TOTAL, outcome="rebuilt") == rebuilt_before + 1


@pytest.mark.parametrize("same_org", [True, False], ids=["other_user", "other_org"])
async def test_another_user_or_organisation_gets_resume_unavailable(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: FakeRedis,
    same_org: bool,
) -> None:
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    await run_ws(world, RecordingSocket(provider))
    (message_id,) = [
        e["message_id"] for e in [json.loads(v) for v in _buffer(fake_redis)] if _final(e)
    ]
    intruder = stranger(principal_for(world), same_org=same_org)
    unavailable_before = counter_value(CHAT_WS_RESUME_TOTAL, outcome="unavailable")

    for expire in (False, True):
        if expire:
            fake_redis.clock.advance(settings.chat_resume_buffer_ttl_seconds * 1000 + 1)  # type: ignore[attr-defined]
        socket = RecordingSocket()
        await run_ws_resume(
            websocket=socket,
            payload={"message_id": message_id, "last_stream_sequence": 0},
            principal=intruder,
            sequence=WsSequence(),
            session_factory=chat_api.SessionLocal,
        )
        assert [(e["event"], e["safe_error_code"]) for e in socket.events] == [
            ("chat.error", "resume_unavailable")
        ]
    assert counter_value(CHAT_WS_RESUME_TOTAL, outcome="unavailable") == unavailable_before + 2


def _buffer(fake: FakeRedis) -> list[str]:
    (items,) = fake.keyspace.lists.values()
    return items


def _final(event: dict[str, Any]) -> bool:
    return bool(event["event"] == "chat.completed")


async def test_grace_zero_cancels_on_drop(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    monkeypatch.setattr(settings, "chat_ws_resume_grace_seconds", 0)
    provider, world = await _world(db_session, monkeypatch, asyncio.Event())
    install_ws(monkeypatch, [principal_for(world)])
    before = counter_value(CHAT_WS_DROP_TOTAL, outcome="cancelled_no_grace")
    await _start_and_drop(world, DroppableSocket())
    await _until(lambda: provider.closed_streams == 1)
    await _until_usage(db_session)
    assert provider.finished_streams == 0
    assert counter_value(CHAT_WS_DROP_TOTAL, outcome="cancelled_no_grace") == before + 1


async def test_grace_expiry_cancels_and_records_partial_usage(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    monkeypatch.setattr(settings, "chat_ws_resume_grace_seconds", 0.1)
    provider, world = await _world(db_session, monkeypatch, asyncio.Event())
    install_ws(monkeypatch, [principal_for(world)])
    before = counter_value(CHAT_WS_DROP_TOTAL, outcome="cancelled")
    await _start_and_drop(world, DroppableSocket())
    await wait_for_watchers()
    assert provider.closed_streams == 1 and provider.finished_streams == 0
    assert await _usage_types(db_session) == ["chat.completion.cancelled"]
    assert counter_value(CHAT_WS_DROP_TOTAL, outcome="cancelled") == before + 1
    assert json.loads(_buffer(fake_redis)[-1])["event"] == "chat.cancelled"


async def test_attached_reader_extends_the_grace_and_its_cancel_reaches_the_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    monkeypatch.setattr(settings, "chat_ws_resume_grace_seconds", 0.1)
    provider, world = await _world(db_session, monkeypatch, asyncio.Event())
    principal = principal_for(world)
    install_ws(monkeypatch, [principal, principal])
    _, message_id, last = await _start_and_drop(world, DroppableSocket())
    second = DroppableSocket()
    connection = connect(second)
    second.push("chat.resume", {"message_id": message_id, "last_stream_sequence": last})
    await second.wait_for("chat.resumed")
    await asyncio.sleep(0.3)  # past the grace window, but a reader is attached
    assert provider.active_streams == 1
    second.push("chat.cancel")
    await second.wait_for("chat.cancelled")
    await wait_for_watchers()
    assert provider.closed_streams == 1 and provider.finished_streams == 0
    second.drop()
    await asyncio.wait_for(connection, timeout=5)
    assert await _usage_types(db_session) == ["chat.completion.cancelled"]


async def test_without_redis_the_run_is_cancelled_on_drop_and_resume_is_unavailable(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    monkeypatch.setattr(settings, "chat_ws_resume_grace_seconds", 30)
    provider, world = await _world(db_session, monkeypatch, asyncio.Event())
    principal = principal_for(world)
    install_ws(monkeypatch, [principal, principal])
    unavailable = counter_value(CHAT_WS_RESUME_TOTAL, outcome="redis_unavailable")
    first = DroppableSocket()
    _, message_id, _last = await _start_and_drop(world, first)
    await _until(lambda: provider.closed_streams == 1)
    await _until_usage(db_session)
    assert stream_sequences(first.run_events())[0] == 1  # numbered without a buffer too

    second = DroppableSocket()
    connection = connect(second)
    second.push("chat.resume", {"message_id": message_id, "last_stream_sequence": 0})
    await second.wait_for("chat.error")
    assert second.of("chat.error")[0]["safe_error_code"] == "resume_unavailable"
    second.drop()
    await asyncio.wait_for(connection, timeout=5)
    assert counter_value(CHAT_WS_RESUME_TOTAL, outcome="redis_unavailable") == unavailable + 1


async def test_failing_redis_never_fails_the_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    errors = counter_value(CHAT_RESUME_BUFFER_ERRORS_TOTAL)
    socket = RecordingSocket(provider)
    await run_ws(world, socket)
    assert "chat.completed" in socket.names()
    assert counter_value(CHAT_RESUME_BUFFER_ERRORS_TOTAL) == errors + 1  # stops after one

    resume = RecordingSocket()
    await run_ws_resume(
        websocket=resume,
        payload={"message_id": str(uuid4())},
        principal=principal_for(world),
        sequence=WsSequence(),
        session_factory=chat_api.SessionLocal,
    )
    assert resume.events[0]["safe_error_code"] == "resume_unavailable"


async def test_invalid_resume_and_resume_while_running(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    hold = asyncio.Event()
    _provider, world = await _world(db_session, monkeypatch, hold)
    install_ws(monkeypatch, [principal_for(world)])
    socket = DroppableSocket()
    connection = connect(socket)
    socket.push("chat.resume", {"message_id": "not-a-uuid"})
    await socket.wait_for("chat.error")
    socket.push("chat.start", {"chat_session_id": None, **world.payload})
    await socket.wait_for("generation.delta")
    socket.push("chat.resume", {"message_id": str(uuid4()), "last_stream_sequence": 0})
    await _until(lambda: len(socket.of("chat.error")) == 2)
    assert [e["safe_error_code"] for e in socket.of("chat.error")] == [
        "invalid_request",
        "already_running",
    ]
    hold.set()
    await socket.wait_for("chat.completed")
    socket.drop()
    await asyncio.wait_for(connection, timeout=5)
    assert parse_resume_payload({"message_id": str(uuid4()), "last_stream_sequence": -1}) is None
    assert parse_resume_payload({"message_id": str(uuid4()), "last_stream_sequence": True}) is None
    assert parse_resume_payload(None) is None


async def test_unknown_message_resume_and_tail_of_an_expiring_buffer(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    principal = principal_for(world)
    socket = RecordingSocket()
    await run_ws_resume(
        websocket=socket,
        payload={"message_id": str(uuid4()), "last_stream_sequence": 0},
        principal=principal,
        sequence=WsSequence(),
        session_factory=chat_api.SessionLocal,
    )
    assert socket.events[0]["safe_error_code"] == "resume_unavailable"

    # A buffer without a terminal event that expires while it is tailed.
    message_id = uuid4()
    key = resume_key(principal.organization_id, principal.user_id, message_id)
    fake_redis.keyspace.rpush(key, json.dumps({"event": "generation.delta", "stream_sequence": 1}))
    fake_redis.keyspace.pexpire(key, 60_000)
    tail = RecordingSocket()
    task = asyncio.create_task(
        run_ws_resume(
            websocket=tail,
            payload={"message_id": str(message_id), "last_stream_sequence": 0},
            principal=principal,
            sequence=WsSequence(),
            session_factory=chat_api.SessionLocal,
        )
    )
    await tail.wait_for("chat.resumed")
    fake_redis.keyspace.delete(key)
    await asyncio.wait_for(task, timeout=5)
    assert [e["event"] for e in tail.events] == ["chat.resumed", "generation.delta", "chat.error"]
    assert tail.events[-1]["safe_error_code"] == "resume_unavailable"


async def _until(condition: Any, timeout: float = 5.0) -> None:
    async def _wait() -> None:
        while not condition():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait(), timeout)


async def _until_usage(db: AsyncSession, timeout: float = 5.0) -> None:
    async def _wait() -> None:
        while await _usage_types(db) != ["chat.completion.cancelled"]:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait(), timeout)
