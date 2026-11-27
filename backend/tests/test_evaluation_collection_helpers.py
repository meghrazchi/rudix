"""Edge cases of the evaluation collection helpers and settings (R06-12)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from inmemory_qdrant import InMemoryQdrant
from qdrant_client.http.exceptions import UnexpectedResponse

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.vector_index.services.generation_service import registry
from app.workers import document_tasks, evaluation_index_cleanup
from app.workers.evaluation import collection as collection_module
from app.workers.evaluation import corpus as corpus_module

EVAL = "rudix_eval_vectors"
PROD = "documents"


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "qdrant_evaluation_collection", EVAL)


@pytest.mark.asyncio
async def test_ensure_creates_once_and_rejects_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InMemoryQdrant()
    client.add_collection(PROD, size=settings.qdrant_vector_size, distance="dot")
    monkeypatch.setattr(settings, "qdrant_collection", PROD)
    monkeypatch.setattr(settings, "qdrant_collection_alias", None)
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    registry.invalidate()
    collection_module.reset_ensured_cache()

    size, distance = await collection_module.ensure_evaluation_collection(EVAL)
    assert (size, distance) == (settings.qdrant_vector_size, "dot")
    assert client.vector_configs[EVAL] == (settings.qdrant_vector_size, "dot")
    created = client.calls["create_collection"]
    await collection_module.ensure_evaluation_collection(EVAL)
    assert client.calls["create_collection"] == created  # cached

    collection_module.reset_ensured_cache()
    client.add_collection("other_eval", size=8, distance="dot")
    with pytest.raises(collection_module.EvaluationCollectionMismatchError, match="differ"):
        await collection_module.ensure_evaluation_collection("other_eval")

    monkeypatch.setattr(settings, "qdrant_vector_size", settings.qdrant_vector_size + 1)
    with pytest.raises(collection_module.EvaluationCollectionMismatchError, match="SIZE"):
        await collection_module.ensure_evaluation_collection(EVAL)
    collection_module.reset_ensured_cache()


@pytest.mark.asyncio
async def test_ensure_recreates_a_collection_dropped_after_it_was_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InMemoryQdrant()
    client.add_collection(PROD, size=settings.qdrant_vector_size)
    monkeypatch.setattr(settings, "qdrant_collection", PROD)
    monkeypatch.setattr(settings, "qdrant_collection_alias", None)
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    registry.invalidate()
    collection_module.reset_ensured_cache()

    await collection_module.ensure_evaluation_collection(EVAL)
    created = client.calls["create_collection"]
    client.delete_collection(collection_name=EVAL)  # an operator drops it; workers keep running

    await collection_module.ensure_evaluation_collection(EVAL)
    assert client.collection_exists(EVAL)
    assert client.calls["create_collection"] == created + 1
    collection_module.reset_ensured_cache()


def test_eval_retrieval_embeds_with_the_reingest_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
    from app.workers.evaluation import target as target_module

    class _IngestEmbedding:
        model_name = " ingest-embedding-model "

    _enable(monkeypatch)
    monkeypatch.setattr(document_tasks, "_embedding_service", _IngestEmbedding())
    service = target_module.retrieval_service_for("eval-0123456789-2")
    assert isinstance(service, QueryRetrievalService)
    # Pinned: not the active generation's model, which may differ in alias mode.
    assert service.embedding_model == "ingest-embedding-model"
    assert service.vector_size == settings.qdrant_vector_size
    assert service.qdrant_collection == EVAL

    monkeypatch.setattr(document_tasks, "_embedding_service", object())
    assert collection_module.reingest_embedding_model() == settings.openai_embedding_model.strip()


@pytest.mark.asyncio
async def test_ensure_falls_back_to_settings_without_a_production_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InMemoryQdrant()
    client.add_collection("unrelated", size=4)
    monkeypatch.setattr(settings, "qdrant_collection", PROD)
    monkeypatch.setattr(settings, "qdrant_collection_alias", None)
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    registry.invalidate()
    collection_module.reset_ensured_cache()

    size, distance = await collection_module.ensure_evaluation_collection(EVAL)
    assert (size, distance) == (settings.qdrant_vector_size, settings.qdrant_distance.value)
    collection_module.reset_ensured_cache()


class _DeleteRecorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    async def delete_document_points(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


def _not_found(status: int = 404) -> UnexpectedResponse:
    return UnexpectedResponse(status, "Not Found", b"", None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_delete_document_evaluation_points_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    org, doc = uuid4(), uuid4()
    recorder = _DeleteRecorder()
    helper = collection_module.delete_document_evaluation_points
    assert await helper(recorder, organization_id=org, document_id=doc) is False
    assert recorder.calls == []

    _enable(monkeypatch)
    assert await helper(recorder, organization_id=org, document_id=doc) is True
    assert recorder.calls == [{"organization_id": org, "document_id": doc, "collection_name": EVAL}]
    assert await helper(_DeleteRecorder(_not_found()), organization_id=org, document_id=doc) is (
        False
    )
    with pytest.raises(UnexpectedResponse):
        await helper(_DeleteRecorder(_not_found(500)), organization_id=org, document_id=doc)


@pytest.mark.asyncio
async def test_cleanup_tolerates_a_missing_eval_collection_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domains.documents.repositories.documents import DocumentRepository

    async def _no_chunks(self: Any, session: Any, **_: Any) -> int:
        return 0

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(DocumentRepository, "delete_document_chunks", _no_chunks)
    monkeypatch.setattr(evaluation_index_cleanup, "SessionLocal", _Session)
    failures: list[str] = []
    monkeypatch.setattr(
        evaluation_index_cleanup,
        "record_eval_index_cleanup_failure",
        lambda *, store: failures.append(store),
    )
    cleanup = evaluation_index_cleanup.cleanup_eval_index_version_async
    kwargs: dict[str, Any] = {
        "organization_id": uuid4(),
        "document_ids": [uuid4()],
        "index_version": "eval-0123456789-1",
    }

    # Legacy mode: a 404 from the production collection is a failure, as before.
    monkeypatch.setattr(document_tasks, "_qdrant_service", _DeleteRecorder(_not_found()))
    assert (await cleanup(**kwargs)).qdrant_failures == 1

    _enable(monkeypatch)
    recorder = _DeleteRecorder(_not_found())
    monkeypatch.setattr(document_tasks, "_qdrant_service", recorder)
    assert (await cleanup(**kwargs)).qdrant_failures == 0
    assert recorder.calls[0]["collection_name"] == EVAL
    monkeypatch.setattr(document_tasks, "_qdrant_service", _DeleteRecorder(_not_found(503)))
    assert (await cleanup(**kwargs)).qdrant_failures == 1
    assert failures == ["qdrant", "qdrant"]


def test_evaluation_collection_must_differ_from_production() -> None:
    from pydantic import ValidationError

    from app.core.settings.workers import WorkersSettings

    assert WorkersSettings().qdrant_evaluation_collection is None
    assert WorkersSettings(qdrant_evaluation_collection=EVAL).qdrant_evaluation_collection == EVAL
    with pytest.raises(ValidationError, match="must differ"):
        WorkersSettings(qdrant_evaluation_collection="live", qdrant_collection_alias="live")
    with pytest.raises(ValidationError, match="must differ"):
        settings.model_validate(
            {**settings.model_dump(), "qdrant_evaluation_collection": settings.qdrant_collection}
        )
    with pytest.raises(ValidationError):
        WorkersSettings(qdrant_evaluation_collection="bad name!")
    assert collection_module.evaluation_collection() is None


def test_corpus_reingest_passes_the_eval_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []

    async def _fake_extract(document_id: str, **kwargs: Any) -> None:
        seen.append(kwargs["options"])

    monkeypatch.setattr(corpus_module, "extract_and_store", _fake_extract)
    from app.workers.async_runtime import run_async

    run_async(
        corpus_module._reingest_document_async(
            uuid4(),
            chunking_service=object(),
            profile_source="inline_profile",
            request_id=None,
            organization_id=None,
            user_id=None,
            vector_collection=EVAL,
        )
    )
    assert seen[0].vector_collection == EVAL
    assert seen[0].persist_document_state is False
    assert seen[0].record_usage_event is False
