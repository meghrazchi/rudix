"""Transactional outbox: request-path dispatch and the ``outbox.relay`` beat task (R06-01).

The upload, delete, reindex, graph reindex, and OCR retry endpoints write their task as an
``outbox_messages`` row in the transaction of the document change and publish it after
commit. A failed publication keeps today's deferred/503 responses and leaves the row
``pending`` for the relay, which publishes it once.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from test_documents_reindex_api import (
    FakeReindexTask,
    _headers,
    _seed_document,
    _seed_org_user,
    fake_reindex_task,  # noqa: F401  (fixture)
    reindex_client,  # noqa: F401  (fixture)
)
from test_documents_upload_api import (
    FakeProcessDocumentTask,
    _auth_headers,
    _seed_principal,
    fake_malware_scan_service,  # noqa: F401  (fixture)
    fake_minio,  # noqa: F401  (fixture)
    fake_process_document_task,  # noqa: F401  (fixture)
    upload_client,  # noqa: F401  (fixture)
)

from app.application import outbox
from app.auth.token_codec import create_app_access_token
from app.core.config import settings
from app.interfaces.http import admin_documents
from app.interfaces.http import documents as documents_api
from app.models.document import Document
from app.models.enums import DocumentStatus, OrganizationRole
from app.models.organization import Organization
from app.models.outbox import OutboxMessage
from app.workers import outbox_tasks
from app.workers.celery_app import BEAT_SCHEDULE, TASK_ROUTES


async def _rows(db_session: AsyncSession) -> list[OutboxMessage]:
    stmt = select(OutboxMessage).execution_options(populate_existing=True)
    return list((await db_session.execute(stmt)).scalars())


def _factory(db_session: AsyncSession) -> Any:
    @asynccontextmanager
    async def _session() -> AsyncIterator[AsyncSession]:
        # The relay begins its own transaction, like a fresh maintenance session.
        await db_session.commit()
        yield db_session

    return _session


class _Broker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.published: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def resolve(self, task_name: str) -> Any:
        broker = self

        class _Task:
            def apply_async(self, *, kwargs: dict[str, Any], **options: Any) -> Any:
                if broker.fail:
                    raise ConnectionError("broker unavailable")
                broker.published.append((task_name, kwargs, options))
                return None

        return _Task()


async def test_upload_commits_the_outbox_row_with_the_document(
    upload_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    fake_minio: Any,  # noqa: F811
    fake_process_document_task: FakeProcessDocumentTask,  # noqa: F811
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 201
    assert response.json()["queue_status"] == "queued"
    document_id = response.json()["document_id"]
    rows = await _rows(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.task_name == "documents.process"
    assert row.organization_id == org.id
    assert row.status == outbox.PUBLISHED
    assert row.attempts == 1
    assert row.dedupe_key == f"documents.process:{document_id}:upload"
    assert row.kwargs == {
        "document_id": document_id,
        "request_id": row.kwargs["request_id"],
        "organization_id": str(org.id),
        "user_id": str(user.id),
    }
    assert len(fake_process_document_task.delay_calls) == 1


async def test_failed_publish_leaves_the_row_pending_and_the_relay_publishes_it_once(
    upload_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    fake_minio: Any,  # noqa: F811
    fake_process_document_task: FakeProcessDocumentTask,  # noqa: F811
) -> None:
    fake_process_document_task.fail_delay = True
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 503
    [row] = await _rows(db_session)
    assert row.status == outbox.PENDING
    assert row.last_error == "RuntimeError"
    assert row.attempts == 1

    broker = _Broker()
    later = datetime.now(UTC) + timedelta(minutes=10)
    counts = await outbox_tasks.relay_pending(
        now=later, session_factory=_factory(db_session), resolver=broker.resolve
    )
    assert counts == {"published": 1, "retried": 0, "failed": 0}
    assert [name for name, _, _ in broker.published] == ["documents.process"]
    assert broker.published[0][1]["document_id"] == response_document_id(row)
    again = await outbox_tasks.relay_pending(
        now=later, session_factory=_factory(db_session), resolver=broker.resolve
    )
    assert again == {"published": 0, "retried": 0, "failed": 0}
    [row] = await _rows(db_session)
    assert row.status == outbox.PUBLISHED and row.published_at is not None
    document = (await db_session.execute(select(Document))).scalar_one()
    assert document.status == DocumentStatus.uploaded.value


def response_document_id(row: OutboxMessage) -> str:
    return str(row.kwargs["document_id"])


async def _org(db_session: AsyncSession) -> Organization:
    org = Organization(name="Outbox", slug=f"outbox-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.commit()
    return org


async def test_broker_failure_backs_off_and_gives_up_after_max_attempts(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org = await _org(db_session)
    await outbox.enqueue(
        db_session,
        organization_id=org.id,
        task_name="documents.delete",
        kwargs={"document_id": str(uuid4())},
        queue="documents.deletion",
    )
    await db_session.commit()
    monkeypatch.setattr(settings, "outbox_max_attempts", 2)
    broker = _Broker(fail=True)
    now = datetime.now(UTC) + timedelta(seconds=1)
    first = await outbox_tasks.relay_pending(
        now=now, session_factory=_factory(db_session), resolver=broker.resolve
    )
    assert first == {"published": 0, "retried": 1, "failed": 0}
    [row] = await _rows(db_session)
    assert row.status == outbox.PENDING and row.attempts == 1
    assert row.last_error == "ConnectionError"
    # Not due again before the backoff elapses.
    assert await outbox_tasks.relay_pending(
        now=now, session_factory=_factory(db_session), resolver=broker.resolve
    ) == {"published": 0, "retried": 0, "failed": 0}
    second = await outbox_tasks.relay_pending(
        now=now + timedelta(minutes=10),
        session_factory=_factory(db_session),
        resolver=broker.resolve,
    )
    assert second == {"published": 0, "retried": 0, "failed": 1}
    [row] = await _rows(db_session)
    assert row.status == outbox.FAILED


async def test_relay_passes_the_stored_queue(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    await outbox.enqueue(
        db_session,
        organization_id=org.id,
        task_name="documents.delete",
        kwargs={"document_id": "d"},
        queue="documents.deletion",
    )
    await db_session.commit()
    broker = _Broker()
    await outbox_tasks.relay_pending(
        now=datetime.now(UTC) + timedelta(seconds=1),
        session_factory=_factory(db_session),
        resolver=broker.resolve,
    )
    assert broker.published == [
        ("documents.delete", {"document_id": "d"}, {"queue": "documents.deletion"})
    ]


async def test_unknown_task_counts_as_a_publish_failure(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    await outbox.enqueue(db_session, organization_id=org.id, task_name="no.such.task", kwargs={})
    await db_session.commit()
    counts = await outbox_tasks.relay_pending(
        now=datetime.now(UTC) + timedelta(seconds=1), session_factory=_factory(db_session)
    )
    assert counts["retried"] == 1
    [row] = await _rows(db_session)
    assert row.last_error == "NotRegistered"


async def test_dedupe_key_conflict_is_a_no_op(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    first = await outbox.enqueue(
        db_session,
        organization_id=org.id,
        task_name="documents.process",
        kwargs={"document_id": "x"},
        dedupe_key="documents.process:x:upload",
        task=FakeProcessDocumentTask(),
    )
    await db_session.commit()
    second = await outbox.enqueue(
        db_session,
        organization_id=org.id,
        task_name="documents.process",
        kwargs={"document_id": "x"},
        dedupe_key="documents.process:x:upload",
    )
    await db_session.commit()
    assert first is not None and second is None
    assert len(await _rows(db_session)) == 1
    # Only the first row is published by this session.
    outcomes = await outbox.publish_after_commit(db_session)
    assert [outcome.message_id for outcome in outcomes] == [first]
    assert outcomes[0].published


async def test_publish_after_commit_without_rows_is_a_no_op(db_session: AsyncSession) -> None:
    assert await outbox.publish_after_commit(db_session) == []
    assert outbox.first_error([]) is None and outbox.first_result([]) is None


async def test_rollback_discards_the_row(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    await outbox.enqueue(db_session, organization_id=org.id, task_name="t", kwargs={})
    await db_session.rollback()
    assert await _rows(db_session) == []


async def test_discard_and_pending_count(db_session: AsyncSession) -> None:
    org = await _org(db_session)
    message_id = await outbox.enqueue(db_session, organization_id=org.id, task_name="t", kwargs={})
    await db_session.commit()
    assert await outbox.pending_count(db_session, organization_id=org.id) == 1
    await outbox.discard(db_session, message_id)
    await outbox.discard(db_session, None)
    await db_session.commit()
    assert await outbox.pending_count(db_session, organization_id=org.id) == 0
    [row] = await _rows(db_session)
    assert row.status == outbox.FAILED and row.last_error == "cancelled"


def test_backoff_is_capped() -> None:
    assert outbox.backoff_seconds(1) == 2
    assert outbox.backoff_seconds(3) == 8
    assert outbox.backoff_seconds(50) == 300


def test_relay_is_scheduled_and_routed() -> None:
    assert BEAT_SCHEDULE["outbox-relay"]["task"] == "outbox.relay"
    assert BEAT_SCHEDULE["outbox-relay"]["schedule"] == settings.outbox_relay_interval_seconds
    assert TASK_ROUTES["outbox.relay"]["queue"] == settings.celery_task_default_queue


def test_relay_task_runs_the_async_body(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _relay() -> dict[str, int]:
        return {"published": 0, "retried": 0, "failed": 0}

    monkeypatch.setattr(outbox_tasks, "relay_pending", _relay)
    assert outbox_tasks.relay_outbox.run() == {"published": 0, "retried": 0, "failed": 0}


async def test_reindex_publish_failure_cancels_the_row_with_the_status_restore(
    reindex_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    fake_reindex_task: FakeReindexTask,  # noqa: F811
) -> None:
    fake_reindex_task.fail_delay = True
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, slug_prefix="obx")
    document = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.indexed
    )
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    response = await reindex_client.post(
        f"/api/v1/documents/{document.id}/reindex",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 503
    [row] = await _rows(db_session)
    # The document went back to indexed, so the dispatch must never run later.
    assert row.task_name == "documents.reindex"
    assert row.status == outbox.FAILED and row.last_error == "cancelled"


async def test_graph_reindex_and_ocr_retry_go_through_the_outbox(
    reindex_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph_task, ocr_task = FakeReindexTask(), FakeReindexTask()
    monkeypatch.setattr(documents_api, "reindex_document_graph_task", graph_task)
    monkeypatch.setattr(admin_documents, "reindex_document_task", ocr_task)
    user, org = await _seed_org_user(db_session, role=OrganizationRole.admin, slug_prefix="obg")
    document = await _seed_document(
        db_session, organization=org, uploader=user, status=DocumentStatus.indexed
    )
    await db_session.execute(
        update(Document).where(Document.id == document.id).values(ocr_quality_status="low")
    )
    await db_session.commit()
    headers = _headers(
        token=create_app_access_token(
            subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
        ),
        organization_id=str(org.id),
    )
    graph = await reindex_client.post(
        f"/api/v1/documents/{document.id}/graph/reindex", headers=headers
    )
    assert graph.status_code == 202
    ocr = await reindex_client.post(
        f"/api/v1/admin/documents/{document.id}/ocr-retry", headers=headers
    )
    assert ocr.status_code in (200, 202), ocr.text
    rows = sorted(await _rows(db_session), key=lambda r: r.task_name)
    assert [(r.task_name, r.status) for r in rows] == [
        ("documents.graph_reindex", outbox.PUBLISHED),
        ("documents.reindex", outbox.PUBLISHED),
    ]
    assert graph_task.delay_calls[0]["document_id"] == str(document.id)
    assert ocr_task.delay_calls[0]["organization_id"] == str(org.id)


@pytest.mark.requires_postgres
async def test_concurrent_relays_publish_each_row_once_on_postgres(
    pg_session_factory: Any,
) -> None:
    import asyncio
    import time

    from sqlalchemy import delete

    async with pg_session_factory() as session:
        org = Organization(name="Outbox PG", slug=f"outbox-pg-{uuid4().hex[:8]}")
        session.add(org)
        await session.flush()
        for number in range(6):
            await outbox.enqueue(
                session,
                organization_id=org.id,
                task_name="documents.delete",
                kwargs={"document_id": str(number)},
            )
        await session.commit()
    published: list[str] = []

    class _SlowTask:
        def apply_async(self, *, kwargs: dict[str, Any], **_: Any) -> None:
            time.sleep(0.05)  # the other relay scans while this one publishes
            published.append(kwargs["document_id"])

    try:
        results = await asyncio.gather(
            *(
                outbox_tasks.relay_pending(
                    now=datetime.now(UTC) + timedelta(seconds=1),
                    session_factory=pg_session_factory,
                    resolver=lambda _name: _SlowTask(),
                )
                for _ in range(2)
            )
        )
        assert sorted(published) == [str(n) for n in range(6)]
        assert sum(result["published"] for result in results) == 6
    finally:
        async with pg_session_factory() as session:
            await session.execute(delete(Organization).where(Organization.id == org.id))
            await session.commit()


@pytest.mark.requires_postgres
async def test_relay_holds_no_row_lock_or_transaction_while_publishing_on_postgres(
    pg_session_factory: Any,
) -> None:
    """The broker call runs outside the claim transaction: a request that marks the same
    row (``publish_after_commit``) or another relay never waits on a slow or down broker."""
    import asyncio

    from sqlalchemy import delete, text

    async with pg_session_factory() as session:
        org = Organization(name="Outbox lock", slug=f"outbox-lock-{uuid4().hex[:8]}")
        session.add(org)
        await session.flush()
        message_id = await outbox.enqueue(
            session, organization_id=org.id, task_name="documents.delete", kwargs={}
        )
        await session.commit()
    loop = asyncio.get_running_loop()
    seen: dict[str, Any] = {}

    async def _probe() -> None:
        async with pg_session_factory() as other, other.begin():
            # NOWAIT raises at once if the relay still held the row lock.
            locked = await other.execute(
                text("SELECT attempts FROM outbox_messages WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": message_id},
            )
            seen["attempts"] = locked.scalar_one()
            idle = await other.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND state = 'idle in transaction' AND pid <> pg_backend_pid()"
                )
            )
            seen["idle_in_transaction"] = idle.scalar_one()

    class _ProbingTask:
        def apply_async(self, *, kwargs: dict[str, Any], **_: Any) -> None:
            asyncio.run_coroutine_threadsafe(_probe(), loop).result(timeout=10)

    try:
        counts = await outbox_tasks.relay_pending(
            now=datetime.now(UTC) + timedelta(seconds=1),
            session_factory=pg_session_factory,
            resolver=lambda _name: _ProbingTask(),
        )
        assert counts == {"published": 1, "retried": 0, "failed": 0}
        # The claim committed before the publish: attempts counted, no lock, no open transaction.
        assert seen == {"attempts": 1, "idle_in_transaction": 0}
        async with pg_session_factory() as session:
            row = await session.get(OutboxMessage, message_id)
            assert row is not None and row.status == outbox.PUBLISHED and row.attempts == 1
    finally:
        async with pg_session_factory() as session:
            await session.execute(delete(Organization).where(Organization.id == org.id))
            await session.commit()


async def test_relay_marks_a_row_failed_only_while_it_is_still_pending(
    db_session: AsyncSession,
) -> None:
    """A row the request path published while the relay's attempt failed stays published."""
    org = await _org(db_session)
    message_id = await outbox.enqueue(
        db_session, organization_id=org.id, task_name="documents.delete", kwargs={}
    )
    await db_session.commit()

    class _RacingTask:
        def apply_async(self, *, kwargs: dict[str, Any], **_: Any) -> None:
            raise ConnectionError("broker unavailable")

    async def _mark_published() -> None:
        await db_session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.id == message_id)
            .values(status=outbox.PUBLISHED)
        )
        await db_session.commit()

    real_factory = _factory(db_session)

    @asynccontextmanager
    async def _factory_with_race() -> AsyncIterator[AsyncSession]:
        async with real_factory() as session:
            if _factory_with_race.calls == 1:  # type: ignore[attr-defined]
                await _mark_published()
            _factory_with_race.calls += 1  # type: ignore[attr-defined]
            yield session

    _factory_with_race.calls = 0  # type: ignore[attr-defined]
    counts = await outbox_tasks.relay_pending(
        now=datetime.now(UTC) + timedelta(seconds=1),
        session_factory=_factory_with_race,
        resolver=lambda _name: _RacingTask(),
    )
    assert counts == {"published": 0, "retried": 1, "failed": 0}
    [row] = await _rows(db_session)
    assert row.status == outbox.PUBLISHED and row.last_error is None
