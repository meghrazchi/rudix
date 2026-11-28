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
