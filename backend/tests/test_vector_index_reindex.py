"""Zero-downtime reindex: resumable build, dual writes, deletes, tasks (R06-08)."""

from __future__ import annotations

from typing import Any

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
)
from vector_index_support import (
    NEW_MODEL,
    NEW_SIZE,
    OLD_MODEL,
    StopBuild,
    VectorIndexEnv,
    make_vector_index_env,
)

from app.core.config import settings
from app.domains.vector_index.services import lifecycle_service
from app.domains.vector_index.services.reindex_service import (
    BuildProgress,
    cursor_from_json,
    cursor_to_json,
)
from app.models.enums import DocumentStatus
from app.workers import vector_index_tasks
from app.workers.base_task import PermanentTaskError


@pytest.fixture
def vi(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    yield from make_vector_index_env(ingestion_env, monkeypatch)


async def _read_status(vi: VectorIndexEnv, seeded: Any) -> str:
    from app.models.document import Document

    async with vi.env.factory() as session:
        document = await session.get(Document, seeded.document_id)
        return str(document.status) if document else "missing"


def test_build_resumes_after_a_kill_without_duplicates(vi: VectorIndexEnv) -> None:
    docs = [vi.seed_indexed(f"doc-{i}") for i in range(3)]
    gen = vi.adopt_and_register()
    vi.provider.calls.clear()
    vi.provider.fail_on_call = 2  # the worker dies while embedding the second document

    with pytest.raises(StopBuild):
        vi.build()

    rows = vi.generations()
    assert rows[2].state == "building"
    assert len(vi.generation_documents(gen.id)) == 1
    first_cursor = cursor_from_json(rows[2].build_cursor)
    assert first_cursor is not None

    progress = vi.build()

    assert progress.finished and progress.verify is not None and progress.verify.passed
    assert progress.documents_written == 2
    expected = sum(vi.chunk_count(doc) for doc in docs)
    points = vi.points(gen.collection_name)
    assert len(points) == expected  # deterministic ids: no duplicates
    assert {p.payload["embedding_model"] for p in points.values()} == {NEW_MODEL}
    assert {len(p.vector) for p in points.values()} == {NEW_SIZE}
    assert len(vi.generation_documents(gen.id)) == 3
    rows = vi.generations()
    assert (rows[2].state, rows[2].documents_done, rows[2].documents_total) == ("verifying", 3, 3)
    assert rows[2].indexed_points == expected == rows[2].expected_points
    reindex_events = [
        e for e in vi.usage_events() if (e.metadata_json or {}).get("reason") == "vector_reindex"
    ]
    assert len(reindex_events) == 3  # the killed document was charged once
    assert {e.organization_id for e in reindex_events} == {d.organization_id for d in docs}
    assert all(e.metadata_json["generation"] == 2 for e in reindex_events)
    assert {e.model_name for e in reindex_events} == {NEW_MODEL}
    # A rerun after completion continues from the final cursor and embeds nothing.
    vi.provider.calls.clear()
    rerun = vi.build(generation=2)
    assert rerun.documents_written == 0 and vi.provider.calls == []
    assert rerun.verify is not None and rerun.verify.passed


def test_rerun_after_a_kill_past_the_upsert_reuses_the_target_vectors(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domains.vector_index.services import reindex_service

    seeded = vi.seed_indexed("doc")
    gen = vi.adopt_and_register()
    original = reindex_service.repo.record_generation_document
    killed: list[bool] = []

    async def _die_once(*args: Any, **kwargs: Any) -> None:
        if not killed:
            killed.append(True)
            raise StopBuild()
        await original(*args, **kwargs)

    monkeypatch.setattr(reindex_service.repo, "record_generation_document", _die_once)
    vi.provider.calls.clear()
    with pytest.raises(StopBuild):
        vi.build()
    embedded = len(vi.provider.calls)
    assert embedded == 1 and vi.generation_documents(gen.id) == {}
    assert len(vi.points(gen.collection_name, seeded)) == vi.chunk_count(seeded)

    progress = vi.build()

    assert len(vi.provider.calls) == embedded  # every vector came from the target
    assert progress.verify is not None and progress.verify.passed
    assert len(vi.points(gen.collection_name, seeded)) == vi.chunk_count(seeded)
    events = [
        e for e in vi.usage_events() if (e.metadata_json or {}).get("reason") == "vector_reindex"
    ]
    assert events == []  # the rerun spent no tokens; the killed run committed nothing


def test_dual_write_during_build(vi: VectorIndexEnv) -> None:
    gen = vi.adopt_and_register()
    vi.provider.calls.clear()

    seeded = vi.seed_indexed("during-build")

    old_points = vi.points(settings.qdrant_collection, seeded)
    new_points = vi.points(gen.collection_name, seeded)
    chunks = vi.chunk_count(seeded)
    assert len(old_points) == len(new_points) == chunks
    assert {p.payload["embedding_model"] for p in old_points.values()} == {OLD_MODEL}
    assert {len(p.vector) for p in old_points.values()} == {1536}
    assert {p.payload["embedding_model"] for p in new_points.values()} == {NEW_MODEL}
    assert {len(p.vector) for p in new_points.values()} == {NEW_SIZE}
    assert set(vi.provider.models()) == {OLD_MODEL, NEW_MODEL}
    assert vi.generation_documents(gen.id) == {seeded.document_id: chunks}
    dual = [
        e
        for e in vi.usage_events()
        if (e.metadata_json or {}).get("reason") == "vector_reindex_dual_write"
    ]
    assert len(dual) == 1 and dual[0].model_name == NEW_MODEL

    # The build skips the document the dual write already holds.
    vi.provider.calls.clear()
    progress = vi.build()
    assert progress.documents_skipped == 1 and progress.documents_written == 0
    assert vi.provider.calls == []
    assert progress.verify is not None and progress.verify.passed

    # A reindex while verifying replaces the document's points in both generations.
    result = vi.process(seeded, "reindex-during-verify", force=True)
    assert result["status"] == DocumentStatus.indexed.value
    assert len(vi.points(gen.collection_name, seeded)) == chunks
    assert len(vi.points(settings.qdrant_collection, seeded)) == chunks


def test_same_model_generation_reuses_the_primary_vectors(vi: VectorIndexEnv) -> None:
    vi.enable_alias()
    vi.run(lifecycle_service.adopt())
    gen = vi.run(lifecycle_service.register_building(embedding_model=OLD_MODEL, vector_size=1536))
    vi.provider.calls.clear()
    seeded = vi.seed_indexed("same-model")
    assert len(vi.provider.calls) == 1  # one embedding call serves both generations
    old = vi.points(settings.qdrant_collection, seeded)
    new = vi.points(gen.collection_name, seeded)
    assert {k: p.vector for k, p in old.items()} == {k: p.vector for k, p in new.items()}


def test_failed_dual_write_never_fails_the_document(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    gen = vi.adopt_and_register()
    original = vi.client.upsert

    def _upsert(*, collection_name: str, **kwargs: Any) -> None:
        if collection_name == gen.collection_name:
            raise RuntimeError("building collection unavailable")
        original(collection_name=collection_name, **kwargs)

    monkeypatch.setattr(vi.client, "upsert", _upsert)
    seeded = vi.seed_indexed("dual-write-fails")

    assert vi.run(_read_status(vi, seeded)) == DocumentStatus.indexed.value
    assert vi.points(settings.qdrant_collection, seeded)
    assert vi.points(gen.collection_name, seeded) == {}
    assert vi.generation_documents(gen.id) == {}

    # The build then fills the document.
    monkeypatch.setattr(vi.client, "upsert", original)
    progress = vi.build()
    assert progress.documents_written == 1 and progress.verify is not None
    assert progress.verify.passed


def test_delete_during_build_removes_points_from_both_generations(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers.ingestion import deletion

    monkeypatch.setattr(deletion, "_delete_objects_by_prefix", lambda **_: 0)
    kept = vi.seed_indexed("kept")
    gone = vi.seed_indexed("gone")
    gen = vi.adopt_and_register()
    vi.build()
    assert vi.points(gen.collection_name, gone) and vi.points(settings.qdrant_collection, gone)

    vi.delete(gone)

    assert vi.points(gen.collection_name, gone) == {}
    assert vi.points(settings.qdrant_collection, gone) == {}
    assert vi.points(gen.collection_name, kept) and vi.points(settings.qdrant_collection, kept)


def test_build_task_reenqueues_until_finished(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(2):
        vi.seed_indexed(f"doc-{i}")
    vi.adopt_and_register()
    monkeypatch.setattr(settings, "vector_index_build_batch_documents", 1)
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(
        vector_index_tasks.build_vector_index,
        "apply_async",
        lambda kwargs=None, **_: sent.append(kwargs or {}),
    )

    first = vector_index_tasks.build_vector_index.run(max_pages=1)

    assert first["finished"] is False and first["pages"] == 1
    assert sent == [{"generation": 2, "max_pages": 1}]
    while sent:
        kwargs = sent.pop()
        result = vector_index_tasks.build_vector_index.run(**kwargs)
    assert result["finished"] is True and result["verified"] is True
    assert vi.generations()[2].state == "verifying"


def test_build_task_without_a_building_generation_is_permanent(vi: VectorIndexEnv) -> None:
    with pytest.raises(PermanentTaskError):
        vector_index_tasks.build_vector_index.run()
    vi.enable_alias()
    vi.run(lifecycle_service.adopt())
    with pytest.raises(PermanentTaskError):
        vector_index_tasks.build_vector_index.run()


def test_drop_retired_beat_task_is_off_by_default(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert vector_index_tasks.drop_retired_vector_indexes.run() == {
        "dropped": [],
        "enabled": False,
    }
    monkeypatch.setattr(settings, "vector_index_auto_drop_retired", True)
    # Still legacy mode: nothing to drop.
    assert vector_index_tasks.drop_retired_vector_indexes.run()["enabled"] is False
    vi.seed_indexed("doc")
    vi.adopt_and_register()
    vi.build()
    vi.run(lifecycle_service.swap(dry_run=False))
    monkeypatch.setattr(settings, "qdrant_retired_grace_hours", 0)
    vi.run(lifecycle_service.rollback(dry_run=False))
    vi.run(lifecycle_service.rollback(dry_run=False))
    result = vector_index_tasks.drop_retired_vector_indexes.run()
    assert result == {"dropped": [1], "enabled": True}
    assert settings.qdrant_collection in vi.client.deleted_collections
    assert vi.generations()[2].state == "active"


def test_cursor_json_round_trip_and_progress_dict() -> None:
    from uuid import uuid4

    cursor = (uuid4(), uuid4())
    assert cursor_from_json(cursor_to_json(cursor)) == cursor
    assert cursor_to_json(None) is None
    assert cursor_from_json({"organization_id": "x"}) is None
    assert cursor_from_json(None) is None
    progress = BuildProgress(generation=3, cursor=None)
    assert progress.as_dict()["verified"] is None


def test_swap_after_build_serves_the_new_model(vi: VectorIndexEnv) -> None:
    seeded = vi.seed_indexed("doc")
    gen = vi.adopt_and_register()
    vi.build()
    vi.run(lifecycle_service.swap(dry_run=False))
    # After the swap, ingestion writes to the new generation only, with the new model.
    vi.provider.calls.clear()
    old_runs = {p.payload["ingest_run_id"] for p in vi.points(settings.qdrant_collection).values()}
    result = vi.process(seeded, "after-swap", force=True)
    assert result["status"] == DocumentStatus.indexed.value
    # Unchanged chunks reuse the new generation's vectors; nothing embeds with the old model.
    assert set(vi.provider.models()) <= {NEW_MODEL}
    new_points = vi.points(gen.collection_name, seeded)
    assert len(new_points) == vi.chunk_count(seeded)
    assert {p.payload["embedding_model"] for p in new_points.values()} == {NEW_MODEL}
    # The reindex run wrote the new generation; the retired one was left as it was.
    assert {p.payload["ingest_run_id"] for p in new_points.values()} != {"vector-index-g2"}
    retired = vi.points(settings.qdrant_collection).values()
    assert {p.payload["ingest_run_id"] for p in retired} == old_runs
