"""Dead-letter queue consumer writes FailedJob rows without executing tasks (R06-05)."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from kombu.serialization import dumps
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import metrics_workers
from app.core.config import RlsEnforcement, settings
from app.db.tenant_context import bind_worker_tenant
from app.models.failed_job import FailedJob
from app.workers import dead_letter, document_tasks, evaluation_tasks  # noqa: F401
from app.workers.celery_app import celery_app
from app.workers.dead_letter import (
    DEAD_LETTER_ERROR_CODE,
    DeadLetterConsumer,
    MalformedDeadLetter,
    handle_dead_letter,
    install_worker_bootsteps,
    parse_dead_letter,
)
from app.workers.ingestion import tasks as _ingest_tasks  # noqa: F401  (registers stages)
from app.workers.queue_metrics import QueueDepthSampler
from tests.conftest import RLS_PROBE_ROLE


class FakeMessage:
    """The parts of ``kombu.Message`` the consumer uses."""

    def __init__(
        self, *, headers: dict[str, Any], body: bytes, content_type: str = "application/json"
    ) -> None:
        self.headers = headers
        self.body = body
        self.content_type = content_type
        self.acked = 0
        self.requeued = 0

    def ack(self) -> None:
        self.acked += 1

    def requeue(self) -> None:
        self.requeued += 1


def _celery_message(
    task_name: str,
    kwargs: dict[str, Any],
    *,
    task_id: str | None = None,
    deaths: int = 5,
    queue: str = "documents.processing",
) -> FakeMessage:
    """A real Celery protocol-2 message as RabbitMQ dead-letters it (``x-death`` added)."""
    message = celery_app.amqp.create_task_message(task_id or str(uuid4()), task_name, (), kwargs)
    content_type, _, body = dumps(message.body, serializer="json")
    headers = dict(message.headers)
    headers["x-death"] = [
        {
            "count": deaths,
            "queue": queue,
            "reason": "delivery_limit",
            "exchange": "rudix.tasks",
            "routing-keys": [queue],
        }
    ]
    headers["x-delivery-count"] = deaths
    raw = body if isinstance(body, bytes) else body.encode()
    return FakeMessage(headers=headers, body=raw, content_type=content_type)


def _never_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("documents.process", "documents.ingest.embed", "evaluations.run"):
        task = celery_app.tasks[name]
        monkeypatch.setattr(task, "run", lambda *a, **k: pytest.fail("task executed"))
        monkeypatch.setattr(task, "apply_async", lambda *a, **k: pytest.fail("task published"))


def _jobs(env: IngestionEnv, organization_id: UUID) -> list[FailedJob]:
    async def _load() -> list[FailedJob]:
        async with env.factory() as session:
            rows = await session.execute(
                select(FailedJob).where(FailedJob.organization_id == organization_id)
            )
            return list(rows.scalars().all())

    return list(env.run_async(_load()))


# ── parsing ────────────────────────────────────────────────────────────────────────────


def test_parse_reads_identity_tenant_and_death_count() -> None:
    org, document = uuid4(), uuid4()
    message = _celery_message(
        "documents.process",
        {"document_id": str(document), "organization_id": str(org)},
        task_id="task-1",
        deaths=6,
    )
    record = parse_dead_letter(message)
    assert record.task_id == "task-1"
    assert record.task_name == "documents.process"
    assert record.organization_id == org and record.document_id == document
    assert record.original_queue == "documents.processing"
    assert record.reason == "delivery_limit"
    assert record.death_count == 6


def test_parse_accepts_protocol_one_bodies() -> None:
    org = uuid4()
    body = json.dumps(
        {
            "task": "evaluations.run",
            "id": "t-1",
            "args": [],
            "kwargs": {"organization_id": str(org)},
        }
    ).encode()
    record = parse_dead_letter(FakeMessage(headers={}, body=body))
    assert (record.task_name, record.task_id, record.organization_id) == (
        "evaluations.run",
        "t-1",
        org,
    )
    assert record.death_count == 0 and record.original_queue is None


@pytest.mark.parametrize(
    "message",
    [
        FakeMessage(headers={"task": "x", "id": "1"}, body=b"not json"),
        FakeMessage(headers={"task": "x", "id": "1"}, body=b"[]"),
        FakeMessage(headers={"task": "x", "id": "1"}, body=b'[[], "kwargs", {}]'),
        FakeMessage(headers={"id": "1"}, body=b"[[], {}, {}]"),
        FakeMessage(
            headers={"task": "x", "id": "1"}, body=b"x", content_type="application/x-pickle"
        ),
        FakeMessage(headers=["not", "a", "dict"], body=b"[[], {}, {}]"),  # type: ignore[arg-type]
    ],
)
def test_parse_rejects_malformed_messages(message: FakeMessage) -> None:
    with pytest.raises(MalformedDeadLetter):
        parse_dead_letter(message)


def test_parse_ignores_bad_death_headers_and_ids() -> None:
    message = FakeMessage(
        headers={
            "task": b"documents.delete",
            "id": "t",
            "x-death": ["junk"],
            "x-delivery-count": True,
        },
        body=json.dumps([[], {"organization_id": "nope", "document_id": None}, {}]).encode(),
    )
    record = parse_dead_letter(message)
    assert record.task_name == "documents.delete"
    assert record.organization_id is None and record.document_id is None
    assert record.death_count == 0


# ── handling ───────────────────────────────────────────────────────────────────────────


def test_poison_message_delivered_twice_writes_one_failed_job(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _never_execute(monkeypatch)
    outcomes: list[str] = []
    monkeypatch.setattr(metrics_workers, "record_dead_letter_message", outcomes.append)
    monkeypatch.setattr(dead_letter, "record_dead_letter_message", outcomes.append)
    seeded = ingestion_env.seed()
    kwargs = {
        "document_id": str(seeded.document_id),
        "organization_id": str(seeded.organization_id),
    }
    first = _celery_message("documents.process", kwargs, task_id="poison-1")
    second = _celery_message("documents.process", kwargs, task_id="poison-1", deaths=10)

    assert handle_dead_letter(first, ingestion_env.factory) == "recorded"
    assert handle_dead_letter(second, ingestion_env.factory) == "duplicate"

    assert (first.acked, first.requeued, second.acked, second.requeued) == (1, 0, 1, 0)
    [job] = _jobs(ingestion_env, seeded.organization_id)
    assert job.task_id == "poison-1"
    assert job.task_name == "documents.process"
    assert job.job_type == "dead_letter"
    assert job.error_code == DEAD_LETTER_ERROR_CODE
    assert job.is_retryable is True
    assert job.status == "failed"
    assert job.queue_name == "documents.processing"
    assert job.entity_type == "document" and job.entity_id == seeded.document_id
    assert job.attempt_count == 5
    assert job.metadata_json["dead_letter"] == {
        "task_name": "documents.process",
        "original_queue": "documents.processing",
        "reason": "delivery_limit",
        "death_count": 5,
    }
    assert outcomes == ["recorded", "duplicate"]


def test_stage_task_dead_letter_maps_to_its_process_task(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _never_execute(monkeypatch)
    seeded = ingestion_env.seed()
    message = _celery_message(
        "documents.ingest.embed",
        {
            "document_id": str(seeded.document_id),
            "organization_id": str(seeded.organization_id),
            "run_id": "run-9",
            "claim_token": "claim-9",
        },
    )
    assert handle_dead_letter(message, ingestion_env.factory) == "recorded"
    [job] = _jobs(ingestion_env, seeded.organization_id)
    # The dashboard retry sends documents.process, which resumes the run at embed.
    assert job.task_name == "documents.process"
    assert job.queue_name == settings.celery_queue_documents_processing
    assert job.metadata_json["stage"] == "embed" and job.metadata_json["run_id"] == "run-9"
    assert job.metadata_json["dead_letter"]["task_name"] == "documents.ingest.embed"


def test_unregistered_task_keeps_its_name_and_queue(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    seeded = ingestion_env.seed()
    message = _celery_message(
        "legacy.removed_task", {"organization_id": str(seeded.organization_id)}, queue="default"
    )
    assert handle_dead_letter(message, ingestion_env.factory) == "recorded"
    [job] = _jobs(ingestion_env, seeded.organization_id)
    assert (job.task_name, job.queue_name, job.entity_id) == (
        "legacy.removed_task",
        "default",
        None,
    )


def test_message_without_tenant_is_acked_and_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dead_letter, "persist_dead_letter", lambda *a, **k: pytest.fail("must not persist")
    )
    message = _celery_message("documents.reap_stale", {})
    assert handle_dead_letter(message) == "no_tenant"
    assert (message.acked, message.requeued) == (1, 0)


def test_malformed_message_is_acked_never_requeued() -> None:
    message = FakeMessage(headers={"task": "x", "id": "1"}, body=b"\xff\xfe")
    assert handle_dead_letter(message) == "malformed"
    assert (message.acked, message.requeued) == (1, 0)
    garbage = FakeMessage(headers={}, body=b"{not json")
    assert handle_dead_letter(garbage) == "malformed"
    assert (garbage.acked, garbage.requeued) == (1, 0)


def test_database_error_requeues(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _broken(*_: Any, **__: Any) -> bool:
        raise OSError("database unavailable")

    monkeypatch.setattr(dead_letter, "persist_dead_letter", _broken)
    message = _celery_message("documents.process", {"organization_id": str(uuid4())})
    assert handle_dead_letter(message) == "error"
    assert (message.acked, message.requeued) == (0, 1)


async def test_persist_requires_a_tenant() -> None:
    record = parse_dead_letter(_celery_message("documents.process", {}))
    with pytest.raises(ValueError, match="without organization"):
        await dead_letter.persist_dead_letter(record)


def test_dead_letter_counter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_workers, "is_metrics_enabled", lambda: True)
    counter = metrics_workers.DEAD_LETTER_MESSAGES_TOTAL.labels(outcome="malformed")
    before = counter._value.get()
    metrics_workers.record_dead_letter_message("malformed")
    assert counter._value.get() == before + 1


# ── bootstep wiring ────────────────────────────────────────────────────────────────────


def test_bootsteps_are_installed_and_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    steps = celery_app.steps["consumer"]
    assert DeadLetterConsumer in steps and QueueDepthSampler in steps
    step = DeadLetterConsumer.__new__(DeadLetterConsumer)
    monkeypatch.setattr(settings, "worker_consume_dead_letter", True)
    monkeypatch.setattr(settings, "celery_queue_type", "classic")
    assert step.include_if(None) is False  # no dead-letter queue in classic mode
    monkeypatch.setattr(settings, "celery_queue_type", "quorum")
    assert step.include_if(None) is True
    monkeypatch.setattr(settings, "worker_consume_dead_letter", False)
    assert step.include_if(None) is False


def test_install_adds_both_steps() -> None:
    class _App:
        def __init__(self) -> None:
            self.steps: dict[str, set[Any]] = {"consumer": set()}

    app = _App()
    install_worker_bootsteps(app)
    assert app.steps["consumer"] == {DeadLetterConsumer, QueueDepthSampler}


def test_consumer_reads_the_dead_letter_queue_without_auto_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[dict[str, Any]] = []

    def _consumer(channel: Any, **kwargs: Any) -> dict[str, Any]:
        created.append({"channel": channel, **kwargs})
        return kwargs

    monkeypatch.setattr(dead_letter, "Consumer", _consumer)
    monkeypatch.setattr(settings, "celery_queue_type", "quorum")
    step = DeadLetterConsumer.__new__(DeadLetterConsumer)
    step.get_consumers("chan")
    [kwargs] = created
    assert kwargs["channel"] == "chan"
    assert kwargs["no_ack"] is False
    assert kwargs["on_message"] is handle_dead_letter
    [queue] = kwargs["queues"]
    assert queue.name == settings.celery_dead_letter_queue
    assert queue.queue_arguments == {"x-queue-type": "quorum"}


# ── PostgreSQL: strict row-level security ─────────────────────────────────────────────


@pytest.fixture
def probe_env(ingestion_env_pg: IngestionEnv) -> Iterator[IngestionEnv]:  # noqa: F811
    env = ingestion_env_pg
    url = os.environ["TEST_DATABASE_URL"]

    async def _grant() -> None:
        async with env.factory() as session, session.begin():
            await session.execute(
                text(
                    "DO $$ BEGIN "
                    f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RLS_PROBE_ROLE}') "
                    f"THEN CREATE ROLE {RLS_PROBE_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
                )
            )
            await session.execute(text(f"GRANT USAGE ON SCHEMA public TO {RLS_PROBE_ROLE}"))
            await session.execute(text(f"GRANT SELECT, INSERT ON failed_jobs TO {RLS_PROBE_ROLE}"))

    async def _revoke() -> None:
        async with env.factory() as session, session.begin():
            await session.execute(text(f"REVOKE ALL ON failed_jobs FROM {RLS_PROBE_ROLE}"))

    env.run_async(_grant())
    engine = create_async_engine(url, poolclass=NullPool)

    @event.listens_for(engine.sync_engine, "connect")
    def _become_probe(dbapi_connection: Any, _: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET ROLE {RLS_PROBE_ROLE}")
        cursor.close()

    probe = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    env.monkeypatch.setattr(settings, "rls_enforcement", RlsEnforcement.strict)
    env.monkeypatch.setattr(env, "probe", probe, raising=False)
    try:
        yield env
    finally:
        env.run_async(engine.dispose())
        env.run_async(_revoke())


@pytest.mark.requires_postgres
def test_dead_letter_write_is_idempotent_under_strict_rls_on_postgres(
    probe_env: IngestionEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    _never_execute(monkeypatch)
    probe = probe_env.probe  # type: ignore[attr-defined]
    first, other = probe_env.seed(), probe_env.seed()
    kwargs = {"document_id": str(first.document_id), "organization_id": str(first.organization_id)}
    message = _celery_message("documents.process", kwargs, task_id="pg-poison")
    again = _celery_message("documents.process", kwargs, task_id="pg-poison")
    assert handle_dead_letter(message, probe) == "recorded"
    assert handle_dead_letter(again, probe) == "duplicate"
    # The same task id in another organisation is a different row (dedupe is tenant scoped).
    elsewhere = _celery_message(
        "documents.process", {"organization_id": str(other.organization_id)}, task_id="pg-poison"
    )
    assert handle_dead_letter(elsewhere, probe) == "recorded"
    assert len(_jobs(probe_env, first.organization_id)) == 1
    assert len(_jobs(probe_env, other.organization_id)) == 1

    async def _visible_to(org: UUID) -> int:
        with bind_worker_tenant(org):
            async with probe() as session:
                rows = await session.execute(select(FailedJob.organization_id))
                return len({row[0] for row in rows})

    # The probe role is subject to RLS: each tenant sees only its own row.
    assert probe_env.run_async(_visible_to(first.organization_id)) == 1
    assert probe_env.run_async(_visible_to(uuid4())) == 0
