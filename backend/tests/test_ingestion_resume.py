"""Kill-and-redeliver: a worker killed inside any stage resumes without duplicates (R06-01).

``_WorkerKilled`` is a ``BaseException``, like the worker process dying: nothing in the
pipeline catches it, so the stage row stays ``running``. The task body then runs again
with the same request id (an ``acks_late`` redelivery) and must finish the run with no
duplicate chunks, vectors, usage events, completion audits, or ``indexed`` writes, and
must not repeat finished work (object reads, embedding batches).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    Seeded,
    ingestion_env,  # noqa: F401  (fixture)
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from sqlalchemy import func, select

from app.core.config import settings
from app.models.document import Document, DocumentChunk
from app.models.document_processing import DocumentProcessingStage, DocumentStageArtifact
from app.models.enums import DocumentStatus
from app.models.usage import AuditLog, UsageEvent
from app.workers import document_tasks
from app.workers.ingestion.stages import (
    chunk,
    clean_detect,
    dlp,
    extract,
    finalize,
    index,
)

TEXT = (
    "Annual leave policy. Employees receive twenty days of paid annual leave each year. "
    "Requests are submitted through the people portal at least two weeks in advance.\n\n"
    "Carry over. Up to five unused days carry over into the first quarter of the next "
    "year. Days that are not used by the end of March expire without compensation.\n\n"
    "Sick leave. Sick leave is separate from annual leave and requires a medical note "
    "after three consecutive days. Managers record sick leave in the absence calendar.\n\n"
    "Travel. Business travel is booked through the travel desk. Economy class applies to "
    "flights under six hours and premium economy applies to longer flights."
)
PROFILE = {"strategy": "token_recursive", "chunk_size_tokens": 25, "chunk_overlap_tokens": 5}
TASK_ID = "delivery-1"


class _WorkerKilled(BaseException):
    """Stands in for the worker process dying mid-stage."""


def _kill_after(module: Any, armed: dict[str, bool]) -> Callable[..., Any]:
    real = module.run

    async def _run(ctx: Any) -> Any:
        outcome = await real(ctx)
        if armed["on"]:
            armed["on"] = False
            raise _WorkerKilled(module.__name__)
        return outcome

    return _run


def _arm(env: IngestionEnv, point: str, armed: dict[str, bool]) -> None:
    stage_modules = {
        "extract": extract,
        "clean_detect": clean_detect,
        "dlp": dlp,
        "chunk": chunk,
        "index": index,
    }
    if point in stage_modules:
        module = stage_modules[point]
        env.monkeypatch.setattr(module, "run", _kill_after(module, armed))
    elif point == "embed":
        # Killed while embedding the second of three batches.
        def _before(call_index: int) -> None:
            if armed["on"] and call_index == 1:
                armed["on"] = False
                raise _WorkerKilled("embed")

        env.fakes.embeddings.before_call = _before
    elif point == "finalize_before_commit":
        real_usage = finalize._record_usage

        async def _usage(*args: Any, **kwargs: Any) -> None:
            await real_usage(*args, **kwargs)
            if armed["on"]:
                armed["on"] = False
                raise _WorkerKilled("finalize before commit")

        env.monkeypatch.setattr(finalize, "_record_usage", _usage)
    elif point == "finalize_after_commit":
        real_after = finalize.after_commit

        async def _after(ctx: Any) -> None:
            if armed["on"]:
                armed["on"] = False
                raise _WorkerKilled("finalize after commit")
            await real_after(ctx)

        env.monkeypatch.setattr(finalize, "after_commit", _after)
    else:  # pragma: no cover - guards the parametrisation
        raise AssertionError(point)


def _count_indexed_writes(env: IngestionEnv) -> list[str]:
    writes: list[str] = []
    repository = document_tasks._document_repository
    real = repository.update_document_status

    async def _spy(session: Any, **kwargs: Any) -> Any:
        if kwargs.get("status") == DocumentStatus.indexed.value:
            writes.append(str(kwargs["document_id"]))
        return await real(session, **kwargs)

    env.monkeypatch.setattr(repository, "update_document_status", _spy)
    return writes


async def _state(env: IngestionEnv, seeded: Seeded) -> dict[str, Any]:
    async with env.factory() as session:
        document = (
            await session.execute(select(Document).where(Document.id == seeded.document_id))
        ).scalar_one()
        chunks = list(
            (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.document_id == seeded.document_id)
                )
            ).scalars()
        )

        async def _count(model: Any, *conditions: Any) -> int:
            stmt = select(func.count()).select_from(model).where(*conditions)
            return int((await session.execute(stmt)).scalar_one())

        return {
            "status": document.status,
            "claim": document.processing_task_id,
            "chunk_count": len(chunks),
            "point_ids": {c.qdrant_point_id for c in chunks if c.qdrant_point_id},
            "usage": await _count(
                UsageEvent,
                UsageEvent.organization_id == seeded.organization_id,
                UsageEvent.event_type == "document.embedding",
            ),
            "audits": await _count(
                AuditLog,
                AuditLog.organization_id == seeded.organization_id,
                AuditLog.action == "document.process.completed",
            ),
            "artifacts": await _count(
                DocumentStageArtifact, DocumentStageArtifact.document_id == seeded.document_id
            ),
            "stage_rows": await _count(
                DocumentProcessingStage,
                DocumentProcessingStage.document_id == seeded.document_id,
                DocumentProcessingStage.status == "completed",
            ),
        }


def _ids(seeded: Seeded) -> dict[str, str]:
    return {"organization_id": str(seeded.organization_id), "user_id": str(seeded.user_id)}


KILL_POINTS = [
    "extract",
    "clean_detect",
    "dlp",
    "chunk",
    "embed",
    "index",
    "finalize_before_commit",
    "finalize_after_commit",
]


def _scenario(env: IngestionEnv, point: str) -> None:
    env.monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    env.set_content(TEXT.encode())

    reference = env.seed()
    expected = env.run_task(
        document_tasks.process_document,
        reference.document_id,
        task_id="reference",
        chunking_profile_config=PROFILE,
    )
    assert expected["chunk_count"] == 6
    reference_state = env.run_async(_state(env, reference))
    env.fakes.reset_calls()
    env.fakes.qdrant.points.clear()

    seeded = env.seed()
    indexed_writes = _count_indexed_writes(env)
    armed = {"on": True}
    _arm(env, point, armed)
    with pytest.raises(_WorkerKilled):
        env.run_task(
            document_tasks.process_document,
            seeded.document_id,
            task_id=TASK_ID,
            chunking_profile_config=PROFILE,
            **_ids(seeded),
        )
    assert armed["on"] is False
    killed = env.run_async(_state(env, seeded))
    # Only a kill after the finalize commit leaves the document indexed.
    committed = point == "finalize_after_commit"
    assert (killed["status"] == DocumentStatus.indexed.value) is committed
    assert killed["usage"] == (1 if committed else 0)
    reads_before = env.fakes.minio.reads
    batches_before = len(env.fakes.embeddings.batches)

    result = env.run_task(
        document_tasks.process_document,
        seeded.document_id,
        task_id=TASK_ID,
        chunking_profile_config=PROFILE,
        **_ids(seeded),
    )
    assert result["status"] == DocumentStatus.indexed.value
    assert result["chunk_count"] == expected["chunk_count"]
    assert result["page_count"] == expected["page_count"]
    assert result["embedding_input_tokens"] == expected["embedding_input_tokens"]

    state = env.run_async(_state(env, seeded))
    assert state["status"] == DocumentStatus.indexed.value
    assert state["claim"] is None
    assert state["chunk_count"] == reference_state["chunk_count"]
    assert state["usage"] == 1
    assert state["audits"] == 1
    # finalize is the only writer of indexed; a kill before its commit rolled the first back.
    rolled_back = 1 if point == "finalize_before_commit" else 0
    assert indexed_writes == [str(seeded.document_id)] * (1 + rolled_back)
    # Artifacts of the finished run are gone; only its stage rows remain.
    assert state["artifacts"] == 0
    assert state["stage_rows"] == 8

    # The object is read again only when extract itself was interrupted.
    assert env.fakes.minio.reads == (2 if point == "extract" else 1)
    embedded = [chunk_id for batch in env.fakes.embeddings.batches for chunk_id in batch]
    assert len(env.fakes.embeddings.batches) == 3
    assert len(embedded) == len(set(embedded)) == 6
    if point in ("index", "finalize_before_commit", "finalize_after_commit"):
        assert len(env.fakes.embeddings.batches) == batches_before
    if point == "embed":
        assert batches_before == 1
    assert reads_before >= 1
    # Final vector set: exactly the chunk rows' points, nothing extra.
    assert env.fakes.qdrant.points == state["point_ids"]
    assert len(state["point_ids"]) == 6


@pytest.mark.parametrize("point", KILL_POINTS)
def test_kill_and_redeliver_resumes_without_duplicates(
    ingestion_env: IngestionEnv,  # noqa: F811
    point: str,
) -> None:
    _scenario(ingestion_env, point)


@pytest.mark.requires_postgres
@pytest.mark.parametrize("point", ["chunk", "embed", "finalize_after_commit"])
def test_kill_and_redeliver_resumes_on_postgres(
    ingestion_env_pg: IngestionEnv,  # noqa: F811
    point: str,
) -> None:
    _scenario(ingestion_env_pg, point)
