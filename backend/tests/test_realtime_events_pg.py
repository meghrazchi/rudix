"""Realtime events on PostgreSQL (R07-07): publication follows the real commit, never a
rollback, and locked status transitions publish once per committed change."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from agent_worker_support import (
    AgentWorkerEnv,
    agent_env_pg,  # noqa: F401  (fixture)
)
from redis_fakes import FakeRedis
from sqlalchemy import delete

from app.clients import redis_client as redis_module
from app.core.config import settings
from app.domains.realtime.events import buffer_key
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.workers import status_tracking
from app.workers.async_runtime import run_async

pytestmark = pytest.mark.requires_postgres


def _entries(redis: FakeRedis, organization_id: UUID) -> list[dict[str, Any]]:
    return [json.loads(raw) for raw in redis.keyspace.lrange(buffer_key(organization_id), 0, -1)]


def _document(organization_id: UUID, user_id: UUID) -> Document:
    return Document(
        organization_id=organization_id,
        uploaded_by_user_id=user_id,
        filename="pg.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"test/{uuid4().hex}.pdf",
        status=DocumentStatus.uploaded.value,
    )


def test_commit_publishes_and_rollback_does_not_on_postgres(
    agent_env_pg: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = agent_env_pg
    redis = FakeRedis()
    monkeypatch.setattr(settings, "realtime_events_enabled", True)
    monkeypatch.setattr(redis_module, "redis_client", redis)
    monkeypatch.setattr(status_tracking, "SessionLocal", env.factory)
    seeded = env.seed()

    async def _scenario() -> UUID:
        async with env.factory() as session:
            session.add(_document(seeded.organization_id, seeded.user_id))
            await session.flush()
            await session.rollback()
        assert _entries(redis, seeded.organization_id) == []
        async with env.factory() as session:
            document = _document(seeded.organization_id, seeded.user_id)
            session.add(document)
            await session.commit()
            document_id = document.id
        # Two concurrent transitions to the same status: the row lock serialises them and
        # the second sees no change, so only one committed change is published.
        await asyncio.gather(
            status_tracking._set_document_status_async(
                str(document_id), status=DocumentStatus.indexed, owner_task_id="t1"
            ),
            status_tracking._set_document_status_async(
                str(document_id), status=DocumentStatus.indexed, owner_task_id="t1"
            ),
        )
        return document_id

    try:
        document_id = run_async(_scenario())
        entries = _entries(redis, seeded.organization_id)
        statuses = [e["payload"]["status"] for e in entries if e["type"] == "document.status"]
        assert statuses == ["uploaded", "indexed"]
        assert all(entry["organization_id"] == str(seeded.organization_id) for entry in entries)
    finally:
        env.execute_sql(delete(Document).where(Document.organization_id == seeded.organization_id))
    assert document_id is not None


def test_open_stream_holds_no_database_transaction_on_postgres(
    agent_env_pg: AgentWorkerEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While a stream is open, no backend of this database is ``idle in transaction``.

    The authentication dependency opens a transaction on the request session, and the
    dependency only exits after the response: without the commit in the endpoint, every
    open stream would pin a pooled connection for ``REALTIME_STREAM_MAX_SECONDS``.
    """
    from agent_worker_support import api_client, headers_for
    from sqlalchemy import text

    from app.application.realtime.stream_http import RealtimeStreamReader

    env = agent_env_pg
    monkeypatch.setattr(settings, "realtime_events_enabled", True)
    monkeypatch.setattr(settings, "realtime_stream_max_seconds", 0.3)
    seeded = env.seed()
    idle_in_transaction: list[int] = []
    original_frames = RealtimeStreamReader.frames

    async def _frames(self: RealtimeStreamReader) -> Any:
        async with env.engine.connect() as probe:
            count = (
                await probe.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND pid <> pg_backend_pid() "
                        "AND state LIKE 'idle in transaction%'"
                    )
                )
            ).scalar_one()
        idle_in_transaction.append(int(count))
        async for frame in original_frames(self):
            yield frame

    monkeypatch.setattr(RealtimeStreamReader, "frames", _frames)

    async def _scenario() -> int:
        async with api_client(env, redis=FakeRedis()) as client:
            headers = await headers_for(env, seeded.user_id, seeded.organization_id)
            response = await client.get("/api/v1/events/stream", headers=headers, timeout=10)
        return response.status_code

    assert run_async(_scenario()) == 200
    assert idle_in_transaction == [0]
