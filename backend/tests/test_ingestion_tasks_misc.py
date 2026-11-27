"""Moved task bodies and helpers: storage, deletion, graph reindex, backfill, resume (R06-01)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
)
from sqlalchemy import func, select

from app.clients import minio_client as minio_module
from app.models.enums import DocumentStatus
from app.models.usage import UsageEvent
from app.workers import document_tasks
from app.workers.base_task import PermanentTaskError, TransientTaskError
from app.workers.ingestion import storage
from app.workers.ingestion.errors import parse_optional_uuid
from app.workers.ingestion.pipeline import completed_run_metrics
from app.workers.ingestion.stages import finalize
from app.workers.ingestion.stages.embed_summary import embedding_result, summarize_parts
from app.workers.ingestion.store import MemoryStageStore


class _Body:
    def __init__(self, data: Any, fail: bool = False) -> None:
        self.data, self.fail, self.closed = data, fail, False

    def read(self) -> Any:
        if self.fail:
            raise OSError("reset")
        return self.data

    def close(self) -> None:
        self.closed = True


class _Minio:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response, self.error = response, error
        self.pages: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.delete_error: Exception | None = None

    def get_object(self, **_: Any) -> Any:
        if self.error is not None:
            raise self.error
        return self.response

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return self.pages.pop(0)

    def delete_object(self, **kwargs: Any) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(kwargs["Key"])


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code}}, "Op")


@pytest.mark.parametrize(
    ("minio", "error"),
    [
        (None, TransientTaskError),
        (_Minio(error=_client_error("NoSuchKey")), PermanentTaskError),
        (_Minio(error=_client_error("AccessDenied")), TransientTaskError),
        (_Minio(error=OSError("down")), TransientTaskError),
        (_Minio(response={}), TransientTaskError),
        (_Minio(response={"Body": _Body(b"", fail=True)}), TransientTaskError),
        (_Minio(response={"Body": _Body("not bytes")}), TransientTaskError),
    ],
)
def test_read_object_bytes_errors(
    monkeypatch: pytest.MonkeyPatch, minio: Any, error: type[Exception]
) -> None:
    monkeypatch.setattr(minio_module, "get_minio_client", lambda: minio)
    with pytest.raises(error):
        storage._read_object_bytes(bucket="b", object_key="k")


def test_delete_objects_by_prefix_pages_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    minio = _Minio()
    minio.pages = [
        {
            "Contents": [{"Key": "p.pdf"}, {"Key": ""}],
            "IsTruncated": True,
            "NextContinuationToken": "t",
        },
        {"Contents": [{"Key": "p.meta.json"}], "IsTruncated": True},
    ]
    monkeypatch.setattr(minio_module, "get_minio_client", lambda: minio)
    assert storage._delete_objects_by_prefix(bucket="b", prefix="p") == 2
    assert minio.deleted == ["p.pdf", "p.meta.json"]

    minio.pages = [{"Contents": [{"Key": "gone"}], "IsTruncated": False}]
    minio.delete_error = _client_error("NoSuchKey")
    assert storage._delete_objects_by_prefix(bucket="b", prefix="p") == 0
    for failure in (_client_error("AccessDenied"), OSError("down")):
        minio.pages = [{"Contents": [{"Key": "x"}], "IsTruncated": False}]
        minio.delete_error = failure
        with pytest.raises(TransientTaskError):
            storage._delete_objects_by_prefix(bucket="b", prefix="p")
    minio.error = OSError("list failed")
    with pytest.raises(TransientTaskError):
        storage._delete_objects_by_prefix(bucket="b", prefix="p")
    monkeypatch.setattr(minio_module, "get_minio_client", lambda: None)
    with pytest.raises(TransientTaskError):
        storage._delete_objects_by_prefix(bucket="b", prefix="p")


def test_object_key_prefix_and_uuid_helpers() -> None:
    assert storage._object_key_prefix(" a/b/c.pdf ") == "a/b/c"
    assert storage._object_key_prefix("a/b.dir/c") == "a/b.dir/c"
    assert storage._object_key_prefix("  ") == ""
    assert parse_optional_uuid(None) is None
    assert parse_optional_uuid("nope") is None


def test_delete_task_skips_and_transitions(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ingestion_env
    assert document_tasks.delete_document.run(str(uuid4()))["status"] == "skipped"
    with pytest.raises(PermanentTaskError):
        document_tasks.delete_document.run("not-a-uuid")
    deleted = env.seed(status=DocumentStatus.deleted.value)
    assert document_tasks.delete_document.run(str(deleted.document_id))["status"] == "skipped"

    monkeypatch.setattr(document_tasks, "set_document_status", lambda *a, **k: False)
    for status in (DocumentStatus.indexed.value, DocumentStatus.delete_requested.value):
        seeded = env.seed(status=status)
        with pytest.raises(TransientTaskError):
            document_tasks.delete_document.run(str(seeded.document_id))


def test_delete_assets_failure_paths(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ingestion_env
    seeded = env.seed()

    def _delete_code() -> str:
        with pytest.raises(Exception) as raised:
            env.run_async(document_tasks._delete_document_assets_async(str(seeded.document_id)))
        return str(raised.value.error_details["code"])  # type: ignore[attr-defined]

    async def _qdrant_fail(**_: Any) -> Any:
        raise ValueError("filter")

    monkeypatch.setattr(env.fakes.qdrant, "delete_document_points", _qdrant_fail)
    assert _delete_code() == "QDRANT_DELETE_FILTER_INVALID"

    async def _qdrant_down(**_: Any) -> Any:
        raise OSError("down")

    monkeypatch.setattr(env.fakes.qdrant, "delete_document_points", _qdrant_down)
    assert _delete_code() == "QDRANT_DELETE_FAILED"

    async def _qdrant_ok(**_: Any) -> Any:
        return None

    monkeypatch.setattr(env.fakes.qdrant, "delete_document_points", _qdrant_ok)
    minio = _Minio(error=OSError("list failed"))
    monkeypatch.setattr(minio_module, "minio_client", minio)
    assert _delete_code() == "SOURCE_OBJECT_DELETE_FAILED"

    with pytest.raises(Exception) as raised:
        env.run_async(document_tasks._delete_document_assets_async("bad-id"))
    assert raised.value.error_details["code"] == "INVALID_DOCUMENT_ID"  # type: ignore[attr-defined]
    with pytest.raises(PermanentTaskError, match="Document not found"):
        env.run_async(document_tasks._delete_document_assets_async(str(uuid4())))


def test_delete_task_terminal_failure_reverts_to_delete_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    monkeypatch.setattr(document_tasks, "set_document_status", lambda d, **k: calls.append(k))
    monkeypatch.setattr(document_tasks, "_record_worker_audit", lambda **k: audits.append(k))
    monkeypatch.setattr("app.workers.notification_helper.emit_notification", lambda **_: None)
    task = document_tasks.delete_document
    task.on_terminal_failure(exc=RuntimeError("x"), args=("doc-1",), kwargs={})
    assert calls[0]["status"] == DocumentStatus.delete_requested
    assert audits[0]["action"] == "document.delete.failed"
    task.on_terminal_failure(exc=RuntimeError("x"), args=(), kwargs={"document_id": 5})
    assert len(calls) == 1

    def _boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(document_tasks, "set_document_status", _boom)
    task.on_terminal_failure(exc=RuntimeError("x"), args=("doc-1",), kwargs={})


def test_process_terminal_failure_ignores_non_string_ids_and_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = document_tasks.process_document
    task.on_terminal_failure(exc=RuntimeError("x"), args=(), kwargs={"document_id": 1})

    def _boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(document_tasks, "mark_document_failed", _boom)
    task.on_terminal_failure(exc=RuntimeError("x"), args=("doc-1",), kwargs={})


def test_graph_reindex_paths(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ingestion_env
    with pytest.raises(PermanentTaskError):
        document_tasks.reindex_document_graph.run("bad-id")
    with pytest.raises(PermanentTaskError):
        document_tasks.reindex_document_graph.run(str(uuid4()))
    empty = env.seed(status=DocumentStatus.indexed.value)
    result = document_tasks.reindex_document_graph.run(str(empty.document_id))
    assert result["status"] == "skipped"

    env.set_content(b"Graph reindex reads the committed chunk rows of the document.")
    seeded = env.seed()
    env.run_task(document_tasks.process_document, seeded.document_id, task_id="g1")
    result = document_tasks.reindex_document_graph.run(str(seeded.document_id))
    assert result["status"] == "completed" and result["chunk_count"] == 1

    async def _fail(*_: Any, **__: Any) -> Any:
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(document_tasks, "_run_document_graph_extraction_async", _fail)
    with pytest.raises(RuntimeError):
        document_tasks.reindex_document_graph.run(str(seeded.document_id))

    for status in (DocumentStatus.deleted.value, DocumentStatus.deleting.value):
        gone = env.seed(status=status)
        with pytest.raises(PermanentTaskError):
            env.run_async(document_tasks._reindex_document_graph_async(str(gone.document_id)))


def test_backfill_dispatches_reindex_for_indexed_documents(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ingestion_env
    seeded = env.seed(status=DocumentStatus.indexed.value)
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        document_tasks.celery_app, "send_task", lambda name, kwargs: sent.append(kwargs)
    )
    result = document_tasks.backfill_documents.run(organization_id=str(seeded.organization_id))
    assert result["dispatched_count"] == 1
    assert sent[0]["document_id"] == str(seeded.document_id)


def test_invalid_chunking_profile_is_permanent(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    seeded = env.seed()
    with pytest.raises(PermanentTaskError, match="chunking_profile_config"):
        env.run_task(
            document_tasks.process_document,
            seeded.document_id,
            task_id="bad-profile",
            chunking_profile_config={"chunk_size_tokens": 10, "chunk_overlap_tokens": 20},
        )


def test_reindex_redelivered_after_commit_restores_indexed_once(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ingestion_env
    env.set_content(b"Reindex redelivery after the finalize commit must not double count.")
    seeded = env.seed()
    ids = {"organization_id": str(seeded.organization_id), "user_id": str(seeded.user_id)}
    real_after = finalize.after_commit
    armed = {"on": True}

    async def _after(ctx: Any) -> None:
        if armed["on"]:
            armed["on"] = False
            raise KeyboardInterrupt
        await real_after(ctx)

    monkeypatch.setattr(finalize, "after_commit", _after)
    with pytest.raises(KeyboardInterrupt):
        env.run_task(document_tasks.reindex_document, seeded.document_id, task_id="r1", **ids)
    result = env.run_task(document_tasks.reindex_document, seeded.document_id, task_id="r1", **ids)
    assert result["status"] == "indexed"

    async def _usage() -> int:
        async with env.factory() as session:
            stmt = select(func.count()).where(UsageEvent.organization_id == seeded.organization_id)
            return int((await session.execute(stmt)).scalar_one())

    assert env.run_async(_usage()) == 1
    assert len(env.fakes.embeddings.batches) == 1
    # A process delivery of the reported run is a plain skip.
    assert (
        env.run_async(completed_run_metrics(str(seeded.document_id), run_id="r1", audit_action="x"))
        is not None
    )
    assert (
        env.run_async(
            completed_run_metrics(
                str(seeded.document_id), run_id="r1", audit_action="document.reindex.completed"
            )
        )
        is None
    )
    assert (
        env.run_async(
            completed_run_metrics(str(seeded.document_id), run_id="other", audit_action="x")
        )
        is None
    )
    assert env.run_async(completed_run_metrics("bad", run_id="r1", audit_action="x")) is None


def test_telemetry_and_cleanup_failures_do_not_fail_the_run(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ingestion_env

    class _BrokenRepository:
        def __getattr__(self, _: str) -> Any:
            async def _fail(*_: Any, **__: Any) -> Any:
                raise RuntimeError("telemetry down")

            return _fail

    class _BrokenAudit:
        async def record(self, *_: Any, **__: Any) -> bool:
            raise RuntimeError("audit down")

    async def _cleanup_fails(self: Any) -> None:
        raise RuntimeError("artifact cleanup failed")

    monkeypatch.setattr(document_tasks, "_pipeline_repository", _BrokenRepository())
    monkeypatch.setattr(document_tasks, "_audit_log_service", _BrokenAudit())
    monkeypatch.setattr(
        "app.workers.ingestion.store.DbStageStore.delete_run_artifacts", _cleanup_fails
    )
    env.set_content(b"Telemetry failures are logged and never fail ingestion.")
    seeded = env.seed()
    result = env.run_task(
        document_tasks.process_document,
        seeded.document_id,
        task_id="telemetry",
        organization_id=str(seeded.organization_id),
    )
    assert result["status"] == "indexed"


def test_summary_of_no_batches_falls_back_to_settings() -> None:
    import asyncio

    from test_ingestion_runner import _ctx

    summary = asyncio.run(summarize_parts(_ctx(MemoryStageStore())))
    assert summary["parts"] == 0 and summary["model_name"]
    result = embedding_result({**summary, "vector_dimension": None})
    assert result.vectors_by_chunk_id == {} and result.batch_count == 0


def test_process_redelivered_after_a_reported_run_is_skipped(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    env.set_content(b"A redelivered message of a finished and reported run is a plain skip.")
    seeded = env.seed()
    ids = {"organization_id": str(seeded.organization_id), "user_id": str(seeded.user_id)}
    first = env.run_task(document_tasks.process_document, seeded.document_id, task_id="p1", **ids)
    again = env.run_task(document_tasks.process_document, seeded.document_id, task_id="p1", **ids)
    assert first["status"] == "indexed"
    assert again == {"document_id": str(seeded.document_id), "status": "skipped"}
    assert len(env.fakes.embeddings.batches) == 1
