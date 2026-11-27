"""Celery tasks bind the tenant of their ``organization_id`` kwarg (R06-01, contract 4.2.7)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
)
from sqlalchemy import select

from app.core import metrics_workers
from app.db import session as db_session_module
from app.db.tenant_context import bind_worker_tenant, get_current_tenant_id
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.workers import base_task, document_tasks
from app.workers.base_task import PermanentTaskError, RudixTask, TenantMismatchError
from app.workers.celery_app import celery_app
from app.workers.ingestion import tasks as ingest_tasks
from app.workers.ingestion import tenant
from app.workers.ingestion.stages.base import StageName


def _probe_task(name: str, seen: list[Any]) -> Any:
    @celery_app.task(bind=True, base=RudixTask, name=name)
    def _task(self: RudixTask, organization_id: str | None = None) -> None:
        seen.append(get_current_tenant_id())

    return _task


def test_call_binds_the_organization_kwarg_and_restores_it() -> None:
    seen: list[Any] = []
    task = _probe_task(f"tests.tenant.{uuid4()}", seen)
    org = uuid4()
    task(organization_id=str(org))
    task(organization_id="not-a-uuid")
    task()
    assert seen == [org, None, None]
    assert get_current_tenant_id() is None


def test_bind_worker_tenant_nests() -> None:
    outer, inner = uuid4(), uuid4()
    with bind_worker_tenant(outer):
        with bind_worker_tenant(str(inner)):
            assert get_current_tenant_id() == inner
        assert get_current_tenant_id() == outer
    assert get_current_tenant_id() is None


async def test_persist_failed_job_binds_the_tenant_and_keeps_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[Any] = []

    async def _insert(_factory: Any, job: Any) -> None:
        captured.append((get_current_tenant_id(), job))

    monkeypatch.setattr(base_task, "_insert_failed_job", _insert)
    org = uuid4()
    await base_task._persist_failed_job(
        task_id="t",
        task_name="documents.process",
        organization_id=str(org),
        document_id=str(uuid4()),
        job_id=None,
        queue_name="documents.processing",
        exc=RuntimeError("boom"),
        attempt_count=1,
        metadata={"stage": "embed", "run_id": "r"},
    )
    [(bound, job)] = captured
    assert bound == org
    assert job.metadata_json == {"stage": "embed", "run_id": "r"}
    assert get_current_tenant_id() is None


def test_tenant_mismatch_writes_no_failed_job_and_skips_terminal_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    persisted: list[Any] = []
    terminal: list[Any] = []
    mismatches: list[str] = []

    async def _persist(**kwargs: Any) -> None:
        persisted.append(kwargs)

    monkeypatch.setattr(base_task, "_persist_failed_job", _persist)
    monkeypatch.setattr(metrics_workers, "record_worker_tenant_mismatch", mismatches.append)
    task = document_tasks.process_document
    monkeypatch.setattr(task, "on_terminal_failure", lambda **kw: terminal.append(kw))
    task.push_request(id="t-1", retries=0, delivery_info={})
    try:
        task.on_failure(
            TenantMismatchError(), "t-1", (), {"document_id": "d", "organization_id": "o"}, None
        )
        task.on_failure(
            PermanentTaskError("other"),
            "t-1",
            (),
            {"document_id": "d", "organization_id": "o"},
            None,
        )
    finally:
        task.pop_request()
    assert mismatches == ["documents.process"]
    assert len(persisted) == 1 and persisted[0]["task_name"] == "documents.process"
    assert len(terminal) == 1


def test_tenant_mismatch_error_is_picklable() -> None:
    import pickle

    restored = pickle.loads(pickle.dumps(TenantMismatchError()))
    assert isinstance(restored, TenantMismatchError)
    assert str(restored) == "tenant_mismatch"


@pytest.mark.parametrize(
    "task",
    [
        document_tasks.process_document,
        document_tasks.reindex_document,
        document_tasks.delete_document,
        document_tasks.reindex_document_graph,
    ],
)
def test_document_tasks_stop_before_any_write_for_another_organization(
    ingestion_env: IngestionEnv,  # noqa: F811
    task: Any,
) -> None:
    env = ingestion_env
    seeded = env.seed()
    with pytest.raises(TenantMismatchError):
        env.run_task(task, seeded.document_id, task_id="t", organization_id=str(uuid4()))
    document = env.run_async(_document(env, seeded.document_id))
    assert document.status == DocumentStatus.uploaded.value
    assert document.processing_task_id is None
    assert env.fakes.minio.reads == 0


async def _document(env: IngestionEnv, document_id: UUID) -> Document:
    async with env.factory() as session:
        stmt = select(Document).where(Document.id == document_id)
        return (await session.execute(stmt)).scalar_one()


def _stage_kwargs(document_id: UUID, organization_id: Any) -> dict[str, Any]:
    return {
        "document_id": str(document_id),
        "organization_id": str(organization_id),
        "run_id": "run",
        "claim_token": "claim",
    }


def test_stage_task_for_another_organization_raises_tenant_mismatch(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    seeded = env.seed()
    task = ingest_tasks.STAGE_TASKS[StageName.extract]
    task.push_request(id="stage-1")
    try:
        with pytest.raises(TenantMismatchError):
            task.run(**_stage_kwargs(seeded.document_id, uuid4()))
        # A missing document (deleted mid-run) stops the chain quietly.
        result = task.run(**_stage_kwargs(uuid4(), seeded.organization_id))
    finally:
        task.pop_request()
    assert result["status"] == "superseded"
    assert env.fakes.minio.reads == 0


def _maintenance(env: IngestionEnv) -> Any:
    @asynccontextmanager
    async def _session() -> AsyncIterator[Any]:
        async with env.factory() as session:
            yield session

    return _session


def test_old_process_message_without_organization_resolves_it(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    seeded = env.seed()
    env.monkeypatch.setattr(db_session_module, "maintenance_session", _maintenance(env))
    seen: list[Any] = []

    def _body(task: Any, document_id: str, **kwargs: Any) -> dict[str, Any]:
        seen.append((kwargs["organization_id"], get_current_tenant_id()))
        return {"status": "ok"}

    env.monkeypatch.setattr(document_tasks, "run_document_task", _body)
    document_tasks.process_document(str(seeded.document_id))
    assert seen == [(str(seeded.organization_id), seeded.organization_id)]
    assert env.run_async(tenant.resolve_document_organization("nope")) is None


def test_tenant_lookup_failure_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def _broken() -> AsyncIterator[Any]:
        raise OSError("maintenance database unreachable")
        yield  # pragma: no cover

    monkeypatch.setattr(db_session_module, "maintenance_session", _broken)
    from app.workers.async_runtime import run_async

    assert run_async(tenant._owner_via_maintenance(uuid4())) is None
    # Unparsable ids are not checked (the task's own validation reports them).
    tenant.ensure_document_tenant("doc-1", str(uuid4()))
    tenant.ensure_document_tenant(str(uuid4()), None)


def test_stage_task_failed_job_identity_and_retry_decision() -> None:
    embed = ingest_tasks.STAGE_TASKS[StageName.embed]
    name, queue, metadata = embed.failed_job_identity({"run_id": "r1"}, "documents.processing")
    assert (name, metadata) == ("documents.process", {"stage": "embed", "run_id": "r1"})
    name, queue, _ = embed.failed_job_identity({"run_id": "r1", "mode": "reindex"}, None)
    assert name == "documents.reindex" and queue == "documents.reindex"
    graph = ingest_tasks.STAGE_TASKS[StageName.graph_extract]
    assert graph.failed_job_identity({"run_id": "r"}, None)[0] == "documents.graph_reindex"
    embed.push_request(id="x", retries=0)
    try:
        assert embed.will_retry(base_task.TransientTaskError("t")) is True
        assert embed.will_retry(PermanentTaskError("p")) is False
        assert embed.will_retry(ValueError("v")) is False
    finally:
        embed.pop_request()
    embed.push_request(id="x", retries=embed.max_retries)
    try:
        assert embed.will_retry(base_task.TransientTaskError("t")) is False
    finally:
        embed.pop_request()


def test_graph_task_terminal_failure_marks_only_the_graph_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[Any] = []

    async def _status(document_id: UUID, *, status: str, run_id: UUID | None = None) -> None:
        writes.append((document_id, status))

    monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _status)
    graph = ingest_tasks.STAGE_TASKS[StageName.graph_extract]
    document_id = uuid4()
    graph.on_terminal_failure(exc=RuntimeError("x"), args=(), kwargs={"document_id": "bad"})
    graph.on_terminal_failure(
        exc=RuntimeError("x"), args=(), kwargs={"document_id": str(document_id)}
    )
    assert writes == [(document_id, "failed")]

    async def _broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _broken)
    graph.on_terminal_failure(
        exc=RuntimeError("x"), args=(), kwargs={"document_id": str(document_id)}
    )
