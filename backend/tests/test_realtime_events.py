"""Realtime events (R07-07): envelope, whitelist, audience, publishing after commit."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_worker_support import (
    AgentWorkerEnv,
    agent_env,  # noqa: F401  (fixture)
)
from redis_fakes import BrokenRedis, FakeRedis
from sqlalchemy import select

from app.application.realtime import publisher
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.domains.agents.services.run_stream import RedisRunEvents, build_run_events
from app.domains.notifications.repositories.notifications import NotificationRepository
from app.domains.realtime.events import (
    AGENT_RUN,
    DOCUMENT_STATUS,
    DOCUMENTS_CHANGED,
    Audience,
    RealtimeEvent,
    buffer_key,
    decode_entry,
    document_status_events,
    safe_payload,
    sequence_key,
)
from app.models.connector_sync import ConnectorSyncRun
from app.models.document import Document
from app.models.enums import DocumentStatus, NotificationEventType, NotificationSeverity
from app.models.incident import Incident
from app.workers import status_tracking


@pytest.fixture
def realtime_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(settings, "realtime_events_enabled", True)
    monkeypatch.setattr(redis_module, "redis_client", redis)
    return redis


def buffered(redis: FakeRedis, organization_id: UUID | str) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in redis.keyspace.lrange(buffer_key(organization_id), 0, -1)]


def _document(organization_id: UUID, user_id: UUID, **fields: Any) -> Document:
    values: dict[str, Any] = {
        "organization_id": organization_id,
        "uploaded_by_user_id": user_id,
        "filename": "Quarterly secrets.pdf",
        "file_type": "pdf",
        "storage_bucket": "documents",
        "storage_object_key": f"test/{uuid4().hex}.pdf",
        "status": DocumentStatus.uploaded.value,
        **fields,
    }
    return Document(**values)


# Envelope, whitelist, audience ---------------------------------------------------------


def test_payload_whitelist_strips_extra_fields_and_long_values() -> None:
    payload = safe_payload(
        DOCUMENT_STATUS,
        {
            "document_id": UUID(int=1),
            "status": DocumentStatus.failed,
            "filename": "Board minutes.pdf",
            "error_message": "Traceback ...",
        },
    )
    assert payload == {"document_id": str(UUID(int=1)), "status": "failed"}
    assert safe_payload(DOCUMENT_STATUS, {"status": "x" * 65}) == {}
    assert safe_payload(DOCUMENTS_CHANGED, {"document_id": "abc"}) == {}
    assert safe_payload("unknown.type", {"status": "ok"}) == {}


def test_build_rejects_unknown_types_and_envelope_has_no_audience() -> None:
    with pytest.raises(ValueError):
        RealtimeEvent.build("chat.message", organization_id="o", payload={}, audience=Audience())
    event = RealtimeEvent.build(
        AGENT_RUN,
        organization_id=UUID(int=2),
        payload={"run_id": "r1", "status": "running", "prompt": "secret"},
        audience=Audience.of(user_ids=["u1"]),
    )
    assert set(event.envelope()) == {"type", "organization_id", "occurred_at", "payload"}
    assert event.envelope()["payload"] == {"run_id": "r1", "status": "running"}
    decoded = decode_entry(event.to_entry(7))
    assert decoded is not None and decoded.id == 7
    assert decoded.event.audience.user_ids == ("u1",)


def test_audience_matching() -> None:
    audience = Audience.of(user_ids=[UUID(int=3), None], roles=["Owner", "admin"])
    assert audience.matches(user_id=str(UUID(int=3)), roles=["viewer"])
    assert audience.matches(user_id="someone", roles=[" ADMIN "])
    assert not audience.matches(user_id="someone", roles=["member"])
    assert Audience.of(all_members=True).matches(user_id="x", roles=[])
    assert not Audience.from_dict("garbage").matches(user_id="x", roles=["owner"])


@pytest.mark.parametrize(
    "raw",
    [b"not json", "[]", '{"id": "1"}', '{"id": 1, "type": "nope", "organization_id": "o"}'],
)
def test_decode_entry_drops_malformed_entries(raw: Any) -> None:
    assert decode_entry(raw) is None


# Publishing ---------------------------------------------------------------------------


async def test_publish_now_buffers_trims_and_publishes(
    realtime_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "realtime_buffer_max_events", 3)
    organization_id = uuid4()
    subscriber = realtime_redis.pubsub()
    from app.domains.realtime.events import channel_name

    await subscriber.subscribe(channel_name(organization_id))
    for index in range(4):
        events = document_status_events(
            organization_id=organization_id,
            document_id=UUID(int=index),
            status="indexed",
            uploader_id=None,
        )
        await publisher.publish_now(events)
    entries = buffered(realtime_redis, organization_id)
    assert [entry["id"] for entry in entries] == [6, 7, 8]
    assert realtime_redis.keyspace.get(sequence_key(organization_id)) == "8"
    assert realtime_redis.keyspace.pttl(sequence_key(organization_id)) == -1  # never expires
    assert 0 < realtime_redis.keyspace.pttl(buffer_key(organization_id)) <= 120_000
    assert len(subscriber.messages) == 8
    assert entries[-1]["audience"] == {"user_ids": [], "roles": [], "all_members": True}


async def test_publish_is_a_no_op_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", redis)
    event = document_status_events(
        organization_id=uuid4(), document_id=uuid4(), status="indexed", uploader_id=None
    )
    await publisher.publish_now(event)
    assert redis.round_trips == 0


async def test_publish_failures_and_missing_redis_never_raise(
    realtime_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = document_status_events(
        organization_id=uuid4(), document_id=uuid4(), status="indexed", uploader_id=None
    )
    await publisher.publish_now(event, redis=BrokenRedis())
    monkeypatch.setattr(redis_module, "redis_client", None)
    await publisher.publish_now(event)
    assert realtime_redis.round_trips == 0


async def test_worker_processes_create_their_own_client_per_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[FakeRedis] = []

    def _factory(config: Any) -> FakeRedis:
        del config
        created.append(FakeRedis())
        return created[-1]

    monkeypatch.setattr(settings, "realtime_events_enabled", True)
    monkeypatch.setattr(redis_module, "redis_client", None)
    monkeypatch.setattr("app.clients.factory.create_redis_client", _factory)
    publisher.use_worker_redis()
    try:
        organization_id = uuid4()
        events = document_status_events(
            organization_id=organization_id, document_id=uuid4(), status="queued", uploader_id=None
        )
        await publisher.publish_now(events)
        await publisher.publish_now(events)
        assert len(created) == 1
        assert len(buffered(created[0], organization_id)) == 4
    finally:
        publisher.use_worker_redis(False)

    def _broken(config: Any) -> Any:
        raise OSError("bad url")

    monkeypatch.setattr("app.clients.factory.create_redis_client", _broken)
    publisher.use_worker_redis()
    try:
        await publisher.publish_now(events)  # logged, never raised
    finally:
        publisher.use_worker_redis(False)


# After commit -------------------------------------------------------------------------


async def test_document_status_is_published_only_after_commit(
    agent_env: AgentWorkerEnv,  # noqa: F811
    realtime_redis: FakeRedis,
) -> None:
    seeded = await agent_env.aseed()
    async with agent_env.factory() as session:
        document = _document(seeded.organization_id, seeded.user_id)
        session.add(document)
        await session.flush()
        assert buffered(realtime_redis, seeded.organization_id) == []
        await session.commit()
    entries = buffered(realtime_redis, seeded.organization_id)
    assert [entry["type"] for entry in entries] == [DOCUMENT_STATUS, DOCUMENTS_CHANGED]
    assert entries[0]["payload"] == {"document_id": str(document.id), "status": "uploaded"}
    assert entries[0]["audience"]["user_ids"] == [str(seeded.user_id)]
    assert entries[0]["audience"]["roles"] == ["admin", "owner"]
    assert entries[1]["payload"] == {}
    assert "Quarterly" not in json.dumps(entries)

    async with agent_env.factory() as session:
        row = (await session.execute(select(Document).where(Document.id == document.id))).scalar()
        assert row is not None
        row.filename = "renamed.pdf"  # not a status change
        await session.commit()
    assert len(buffered(realtime_redis, seeded.organization_id)) == 2


async def test_rolled_back_transaction_publishes_nothing(
    agent_env: AgentWorkerEnv,  # noqa: F811
    realtime_redis: FakeRedis,
) -> None:
    seeded = await agent_env.aseed()
    async with agent_env.factory() as session:
        session.add(_document(seeded.organization_id, seeded.user_id))
        await session.flush()
        await session.rollback()
    async with agent_env.factory() as session:
        async with session.begin():
            session.add(_document(seeded.organization_id, seeded.user_id))
            await session.flush()
            nested = await session.begin_nested()
            await nested.commit()  # a SAVEPOINT release publishes nothing
            assert buffered(realtime_redis, seeded.organization_id) == []
            await session.rollback()
    assert buffered(realtime_redis, seeded.organization_id) == []
    assert "PUBLISH" not in realtime_redis.commands


async def test_status_transitions_publish_and_survive_a_broken_redis(
    agent_env: AgentWorkerEnv,  # noqa: F811
    realtime_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = await agent_env.aseed()
    async with agent_env.factory() as session:
        document = _document(seeded.organization_id, seeded.user_id)
        session.add(document)
        await session.commit()
    monkeypatch.setattr(status_tracking, "SessionLocal", agent_env.factory)
    claim = await status_tracking._claim_document_for_processing_async(
        str(document.id), task_id="task-1", force=False
    )
    assert claim.outcome == "claimed"
    statuses = [
        e["payload"].get("status") for e in buffered(realtime_redis, seeded.organization_id)
    ]
    assert statuses[-2:] == ["processing", None]

    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    assert await status_tracking._set_document_status_async(
        str(document.id), status=DocumentStatus.indexed, clear_processing_claim=True
    )
    async with agent_env.factory() as session:
        row = (await session.execute(select(Document).where(Document.id == document.id))).scalar()
        assert row is not None and row.status == DocumentStatus.indexed.value

    monkeypatch.setattr(redis_module, "redis_client", realtime_redis)
    failed = await status_tracking._mark_document_failed_async(
        str(document.id), error_message="boom", owner_task_id=None, protected_statuses=()
    )
    assert failed.outcome == "updated"
    last = buffered(realtime_redis, seeded.organization_id)[-2]
    assert last["payload"] == {"document_id": str(document.id), "status": "failed"}
    assert "boom" not in json.dumps(buffered(realtime_redis, seeded.organization_id))


async def test_claim_records_nothing_when_disabled(
    agent_env: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(redis_module, "redis_client", redis)
    seeded = await agent_env.aseed()
    async with agent_env.factory() as session:
        document = _document(seeded.organization_id, seeded.user_id)
        session.add(document)
        await session.commit()
    monkeypatch.setattr(status_tracking, "SessionLocal", agent_env.factory)
    await status_tracking._claim_document_for_processing_async(
        str(document.id), task_id="task-1", force=False
    )
    assert buffered(redis, seeded.organization_id) == []
    assert "PUBLISH" not in redis.commands


async def test_notification_goes_to_the_recipient_only(
    agent_env: AgentWorkerEnv,  # noqa: F811
    realtime_redis: FakeRedis,
) -> None:
    seeded = await agent_env.aseed()
    async with agent_env.factory() as session:
        notification = await NotificationRepository().create_notification(
            session,
            organization_id=seeded.organization_id,
            user_id=seeded.user_id,
            event_type=next(iter(NotificationEventType)),
            severity=next(iter(NotificationSeverity)),
            title="Your private report is ready",
            message="Contains private text",
        )
        await session.commit()
    (entry,) = buffered(realtime_redis, seeded.organization_id)
    assert entry["type"] == "notification.created"
    assert entry["payload"] == {"notification_id": str(notification.id)}
    assert entry["audience"] == {
        "user_ids": [str(seeded.user_id)],
        "roles": [],
        "all_members": False,
    }
    assert "private" not in json.dumps(entry)


async def test_incident_and_sync_run_changes_publish(
    agent_env: AgentWorkerEnv,  # noqa: F811
    realtime_redis: FakeRedis,
) -> None:
    from datetime import UTC, datetime

    seeded = await agent_env.aseed()
    async with agent_env.factory() as session:
        incident = Incident(
            organization_id=seeded.organization_id,
            title="Indexing delayed",
            status="investigating",
            started_at=datetime.now(UTC),
        )
        run = ConnectorSyncRun(
            organization_id=seeded.organization_id,
            sync_job_id=uuid4(),
            connection_id=uuid4(),
            sync_version=1,
            status="queued",
        )
        session.add_all([incident, run])
        await session.commit()
        incident.status = "resolved"
        run.items_seen = 3  # not a status change
        await session.commit()
        run.status = "completed"
        await session.commit()
        await session.delete(incident)
        await session.delete(run)
        await session.commit()
    entries = buffered(realtime_redis, seeded.organization_id)
    summary = [(entry["type"], entry["payload"].get("status")) for entry in entries]
    assert sorted(summary[:2]) == [("connector.sync", "queued"), ("incident", "investigating")]
    assert summary[2:] == [
        ("incident", "resolved"),
        ("connector.sync", "completed"),
        ("incident", "resolved"),
    ]
    sync = entries[-2]
    assert sync["payload"] == {
        "connection_id": str(run.connection_id),
        "run_id": str(run.id),
        "status": "completed",
    }
    assert sync["audience"]["roles"] == ["admin", "owner"]
    assert "Indexing delayed" not in json.dumps(entries)


async def test_agent_run_level_events_reach_the_realtime_stream(
    realtime_redis: FakeRedis,
) -> None:
    organization_id, run_id, user_id = uuid4(), uuid4(), uuid4()
    events = build_run_events(
        realtime_redis, organization_id=organization_id, run_id=run_id, user_id=user_id
    )
    assert isinstance(events, RedisRunEvents)
    await events.emit("agent.run.status", {"status": "running"})
    await events.emit("agent.step.started", {"sequence": 1, "step_name": "search"})
    await events.emit("agent.run.completed", {"status": "completed", "steps_executed": 2})
    entries = buffered(realtime_redis, organization_id)
    assert [(e["type"], e["payload"]["status"]) for e in entries] == [
        ("agent.run", "running"),
        ("agent.run", "completed"),
    ]
    assert entries[0]["audience"] == {
        "user_ids": [str(user_id)],
        "roles": ["admin", "owner"],
        "all_members": False,
    }


async def test_sync_lease_publishes_running(
    agent_env: AgentWorkerEnv,  # noqa: F811
    realtime_redis: FakeRedis,
) -> None:
    from app.domains.connectors.services.sync import runner

    seeded = await agent_env.aseed()
    async with agent_env.factory() as session:
        run = ConnectorSyncRun(
            organization_id=seeded.organization_id,
            sync_job_id=uuid4(),
            connection_id=uuid4(),
            sync_version=1,
            status="running",
        )
        session.add(run)
        await session.flush()
        await runner._record_sync_status(session, run)
        await session.commit()
    statuses = [e["payload"]["status"] for e in buffered(realtime_redis, seeded.organization_id)]
    assert statuses == ["running", "running"]


async def test_after_commit_without_async_context_skips_publishing(
    realtime_redis: FakeRedis,
) -> None:
    from sqlalchemy.orm import Session

    session = Session()
    try:
        publisher.record_realtime_event(
            session,
            document_status_events(
                organization_id=uuid4(), document_id=uuid4(), status="indexed", uploader_id=None
            ),
        )
        await asyncio.to_thread(session.commit)  # sync commit: cannot await Redis
    finally:
        session.close()
    assert realtime_redis.round_trips == 0
