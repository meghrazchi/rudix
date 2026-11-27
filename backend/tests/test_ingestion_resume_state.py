"""Resume keeps document state that finished stages wrote, and failed runs drop artifacts.

Review fixes of R06-01 part 1:

- Every delivery of ``documents.process`` / ``.reindex`` marks the graph status ``pending``
  (and clears the graph run id) before the pipeline runs. A redelivery that skips the
  completed ``graph_extract`` stage must restore what that stage left, not keep ``pending``.
- A terminal failure acks the message, so the run is never resumed; its artifacts (copies
  of the document text, for a DLP block the flagged text) are deleted.
- A batch-size change between deliveries must not skip rows or count tokens twice.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    Seeded,
    ingestion_env,  # noqa: F401  (fixture)
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from sqlalchemy import func, select
from test_ingestion_golden import PII_TEXT
from test_ingestion_resume import PROFILE, TEXT, _arm, _ids, _WorkerKilled

from app.core.config import settings
from app.models.document import Document
from app.models.document_processing import DocumentStageArtifact
from app.models.enums import DocumentStatus, GraphExtractionStatus
from app.models.usage import UsageEvent
from app.workers import document_tasks
from app.workers.ingestion import task_base
from app.workers.ingestion.stages import graph_extract

TASK_ID = "delivery-state"


async def _graph_state(env: IngestionEnv, seeded: Seeded) -> tuple[str | None, Any]:
    async with env.factory() as session:
        row = (
            await session.execute(
                select(Document.graph_extraction_status, Document.graph_extraction_run_id).where(
                    Document.id == seeded.document_id
                )
            )
        ).one()
    return row[0], row[1]


async def _artifact_count(env: IngestionEnv, seeded: Seeded) -> int:
    async with env.factory() as session:
        stmt = (
            select(func.count())
            .select_from(DocumentStageArtifact)
            .where(DocumentStageArtifact.document_id == seeded.document_id)
        )
        return int((await session.execute(stmt)).scalar_one())


def _kill_then_redeliver(env: IngestionEnv, seeded: Seeded, point: str, task: Any) -> Any:
    armed = {"on": True}
    _arm(env, point, armed)
    kwargs = {"task_id": TASK_ID, "chunking_profile_config": PROFILE, **_ids(seeded)}
    with pytest.raises(_WorkerKilled):
        env.run_task(task, seeded.document_id, **kwargs)
    assert armed["on"] is False
    return env.run_task(task, seeded.document_id, **kwargs)


@pytest.mark.requires_postgres
@pytest.mark.parametrize("point", ["embed", "index", "finalize_before_commit"])
def test_resumed_process_run_keeps_the_graph_status_on_postgres(
    ingestion_env_pg: IngestionEnv,  # noqa: F811
    point: str,
) -> None:
    env = ingestion_env_pg
    env.monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    env.set_content(TEXT.encode())
    seeded = env.seed()
    result = _kill_then_redeliver(env, seeded, point, document_tasks.process_document)
    assert result["status"] == DocumentStatus.indexed.value
    # Graph extraction is disabled in the harness: the finished stage left ``skipped``.
    status, _ = env.run_async(_graph_state(env, seeded))
    assert status == GraphExtractionStatus.skipped.value


@pytest.mark.requires_postgres
def test_redelivered_reindex_after_commit_keeps_the_graph_status_on_postgres(
    ingestion_env_pg: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env_pg
    env.set_content(TEXT.encode())
    seeded = env.seed()
    env.run_task(
        document_tasks.process_document, seeded.document_id, task_id="first", **_ids(seeded)
    )
    result = _kill_then_redeliver(
        env, seeded, "finalize_after_commit", document_tasks.reindex_document
    )
    assert result["status"] == DocumentStatus.indexed.value
    status, _ = env.run_async(_graph_state(env, seeded))
    assert status == GraphExtractionStatus.skipped.value


def test_skipped_graph_stage_restores_status_and_run_id(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    env.monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    env.set_content(TEXT.encode())
    graph_run = uuid4()
    writes: list[tuple[str, UUID | None]] = []

    async def _status(document_id: UUID, *, status: str, run_id: UUID | None = None) -> None:
        writes.append((status, run_id))

    real_state = graph_extract._graph_state

    async def _state(ctx: Any) -> tuple[str | None, str | None]:
        await real_state(ctx)
        return GraphExtractionStatus.completed.value, str(graph_run)

    env.monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _status)
    env.monkeypatch.setattr(graph_extract, "_graph_state", _state)
    seeded = env.seed()
    _kill_then_redeliver(env, seeded, "embed", document_tasks.process_document)
    # First delivery: pending, then the stage ran (status written by graph extraction,
    # recorded here as ``skipped`` by the disabled-graph path). Redelivery: pending, then
    # the skipped stage restores what the stage recorded.
    assert writes[-2] == (GraphExtractionStatus.pending.value, None)
    assert writes[-1] == (GraphExtractionStatus.completed.value, graph_run)


def test_graph_stage_on_skip_without_recorded_status_is_a_no_op() -> None:
    calls: list[Any] = []

    class _Deps:
        async def update_document_graph_status_async(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

    class _Ctx:
        document_id = uuid4()
        deps = _Deps()

    from app.workers.async_runtime import run_async

    run_async(graph_extract.on_skip(_Ctx(), {"entity_count": 0}))  # type: ignore[arg-type]
    run_async(
        graph_extract.on_skip(_Ctx(), {"graph_status": "skipped", "graph_run_id": None})  # type: ignore[arg-type]
    )
    assert calls == [((_Ctx.document_id,), {"status": "skipped", "run_id": None})]


@pytest.mark.parametrize("action", ["quarantine", "reject"])
def test_dlp_block_terminal_failure_discards_the_run_artifacts(
    ingestion_env: IngestionEnv,  # noqa: F811
    action: str,
) -> None:
    env = ingestion_env
    env.monkeypatch.setattr(settings, "dlp_action", action)
    env.set_content(PII_TEXT.encode())
    seeded = env.seed()
    task = document_tasks.process_document
    task.push_request(id=TASK_ID)
    try:
        with pytest.raises(Exception) as raised:
            task.run(str(seeded.document_id), **_ids(seeded))
        assert raised.value.error_details["code"] == "DLP_POLICY_BLOCKED"  # type: ignore[attr-defined]
        # The failed run left its extracted and cleaned pages behind.
        assert env.run_async(_artifact_count(env, seeded)) > 0
        task.on_terminal_failure(exc=raised.value, args=(str(seeded.document_id),), kwargs={})
    finally:
        task.pop_request()
    assert env.run_async(_artifact_count(env, seeded)) == 0


def test_transient_failure_keeps_artifacts_for_the_retry(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    env.monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    env.set_content(TEXT.encode())
    seeded = env.seed()

    def _fail(call_index: int) -> None:
        if call_index == 1:
            raise RuntimeError("provider down")

    env.fakes.embeddings.before_call = _fail
    with pytest.raises(Exception):  # noqa: B017 - the stage maps it to a pipeline error
        env.run_task(
            document_tasks.process_document,
            seeded.document_id,
            task_id=TASK_ID,
            chunking_profile_config=PROFILE,
            **_ids(seeded),
        )
    # No terminal failure yet: the retry resumes from these artifacts.
    assert env.run_async(_artifact_count(env, seeded)) > 0


def test_terminal_failure_artifact_cleanup_error_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[dict[str, Any]] = []

    class _Logger:
        def warning(self, event: str, **fields: Any) -> None:
            warnings.append({"event": event, **fields})

    def _boom(coro: Any) -> Any:
        coro.close()
        raise RuntimeError("database down")

    monkeypatch.setattr(task_base, "logger", _Logger())
    monkeypatch.setattr(document_tasks, "_run", _boom)
    document_id = str(uuid4())
    task_base._discard_failed_run_artifacts(task_base.current_deps(), document_id, "run-1")
    task_base._discard_failed_run_artifacts(task_base.current_deps(), "doc-1", "run-1")
    task_base._discard_failed_run_artifacts(task_base.current_deps(), document_id, None)
    assert warnings == [
        {
            "event": "ingestion.failed_run_artifact_cleanup_error",
            "document_id": document_id,
            "run_id": "run-1",
            "error_type": "RuntimeError",
        }
    ]


def test_batch_size_change_between_deliveries_re_embeds_every_batch(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    env.monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    env.set_content(TEXT.encode())
    reference = env.seed()
    expected = env.run_task(
        document_tasks.process_document,
        reference.document_id,
        task_id="reference",
        chunking_profile_config=PROFILE,
    )
    env.fakes.reset_calls()
    seeded = env.seed()
    armed = {"on": True}
    _arm(env, "embed", armed)
    kwargs = {"task_id": TASK_ID, "chunking_profile_config": PROFILE, **_ids(seeded)}
    with pytest.raises(_WorkerKilled):
        env.run_task(document_tasks.process_document, seeded.document_id, **kwargs)
    first_attempt = len(env.fakes.embeddings.batches)
    assert first_attempt == 1

    env.monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 4)
    result = env.run_task(document_tasks.process_document, seeded.document_id, **kwargs)
    redelivered = env.fakes.embeddings.batches[first_attempt:]
    embedded = [chunk_id for batch in redelivered for chunk_id in batch]
    # Every row embedded again with the new boundaries, none twice in this delivery.
    assert [len(batch) for batch in redelivered] == [4, 2]
    assert len(embedded) == len(set(embedded)) == 6
    assert result["embedding_input_tokens"] == expected["embedding_input_tokens"]

    async def _usage_tokens() -> list[int]:
        async with env.factory() as session:
            rows = await session.execute(
                select(UsageEvent.input_tokens).where(
                    UsageEvent.organization_id == seeded.organization_id,
                    UsageEvent.event_type == "document.embedding",
                )
            )
            return [int(value or 0) for (value,) in rows]

    assert env.run_async(_usage_tokens()) == [expected["embedding_input_tokens"]]
