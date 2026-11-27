"""R06-08 review fixes: query pinning across a swap, stale generation rows, missing collections.

- A query embedded before this process sees a swap is searched in the generation its
  model fills (``read_target_for_vector``), and the embedding cache never stores one
  model's vector under another model's key.
- A document reindexed while a generation is not a write target (failed) loses its row
  there, so a rerun of the build writes it again instead of skipping stale points.
- A document delete tolerates a generation whose collection is already gone.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
)
from qdrant_client.http.exceptions import UnexpectedResponse
from vector_index_support import (
    NEW_MODEL,
    NEW_SIZE,
    OLD_MODEL,
    VectorIndexEnv,
    make_vector_index_env,
)

from app.core.config import settings
from app.domains.ai.providers.protocols import EmbeddingRequest, EmbeddingResponse
from app.domains.chat.services import query_embedding_cache
from app.domains.chat.services.query_embedding_cache import embed_query_cached
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.vector_index.services import generation_service, lifecycle_service

OLD_SIZE = 1536


@pytest.fixture
def vi(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    yield from make_vector_index_env(ingestion_env, monkeypatch)


class SwapDuringEmbed:
    """Provider that swaps the alias while the first embedding call is in flight."""

    def __init__(self, vi: VectorIndexEnv) -> None:
        self.vi = vi
        self.swapped = False

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if not self.swapped:
            self.swapped = True
            await lifecycle_service.swap(dry_run=False)
        return await self.vi.provider.embed(request)


def _record_searches(vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    searched: list[str] = []
    original = vi.client.query_points

    def _query_points(*, collection_name: str, **kwargs: Any) -> Any:
        searched.append(collection_name)
        return original(collection_name=collection_name, **kwargs)

    monkeypatch.setattr(vi.client, "query_points", _query_points)
    return searched


def _built(vi: VectorIndexEnv) -> tuple[Any, Any]:
    seeded = vi.seed_indexed("doc")
    gen = vi.adopt_and_register()
    progress = vi.build()
    assert progress.verify is not None and progress.verify.passed
    return seeded, gen


def test_query_embedded_before_a_swap_searches_the_retired_generation(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded, gen = _built(vi)
    searched = _record_searches(vi, monkeypatch)
    service = QueryRetrievalService(embedding_provider=vi.provider)  # type: ignore[arg-type]
    vector, _ = vi.run(service.embed_query(question="annual leave?"))
    assert len(vector) == OLD_SIZE and vi.provider.models()[-1] == OLD_MODEL

    vi.run(lifecycle_service.swap(dry_run=False))
    candidates = vi.run(
        service.aretrieve_candidates(
            query_vector=vector,
            organization_id=seeded.organization_id,
            document_ids=None,
            initial_top_k=5,
            qdrant_client=vi.client,  # type: ignore[arg-type]
        )
    )

    # The retrieval refreshed the registry (new generation active) but the old-model
    # vector went to the retired collection its model fills, and found the document.
    assert service.embedding_model == NEW_MODEL
    assert searched == [settings.qdrant_collection]
    assert candidates and {str(c.document_id) for c in candidates} == {str(seeded.document_id)}

    # A vector of the active dimension searches the active generation; an unknown
    # dimension falls back to the active one too.
    assert service.search_collection([0.0] * NEW_SIZE) == gen.collection_name
    assert service.search_collection([0.0] * 3) == gen.collection_name
    assert generation_service.read_target_for_vector(OLD_SIZE)[1].embedding_model == OLD_MODEL


def test_rollback_in_flight_query_searches_the_generation_it_left(
    vi: VectorIndexEnv,
) -> None:
    _, gen = _built(vi)
    vi.run(lifecycle_service.swap(dry_run=False))
    vi.run(lifecycle_service.rollback(dry_run=False))
    vi.run(generation_service.registry.snapshot())
    # Active is generation 1 again; a new-model vector embedded before the rollback
    # finds generation 2, now retired.
    assert generation_service.read_target_for_vector(NEW_SIZE)[0] == gen.collection_name
    assert generation_service.read_target_for_vector(OLD_SIZE)[0] == settings.qdrant_collection


def test_embed_query_keeps_the_model_it_started_with(vi: VectorIndexEnv) -> None:
    _built(vi)
    provider = SwapDuringEmbed(vi)
    service = QueryRetrievalService(embedding_provider=provider)  # type: ignore[arg-type]

    # The swap lands while the provider call is in flight: the size check uses the
    # model the call was made with, so the query does not fail.
    vector, _ = vi.run(service.embed_query(question="annual leave?"))

    assert provider.swapped
    assert len(vector) == OLD_SIZE and vi.provider.models()[-1] == OLD_MODEL
    assert service.embedding_model == NEW_MODEL


def test_cache_never_stores_one_models_vector_under_another_models_key(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    _built(vi)
    service = QueryRetrievalService(embedding_provider=vi.provider)  # type: ignore[arg-type]
    stored: list[tuple[str, list[float]]] = []

    async def _get_or_load(*, key_id: str, loader: Any, **_: Any) -> Any:
        # Another request refreshes the shared registry during the cache lookup.
        await lifecycle_service.swap(dry_run=False)
        vector = await loader()
        stored.append((key_id, vector))
        return vector

    monkeypatch.setattr(query_embedding_cache, "get_or_load", _get_or_load)
    result = vi.run(embed_query_cached(service, organization_id=uuid4(), question="leave?"))

    old_key = query_embedding_cache.query_embedding_key(
        model=OLD_MODEL,
        dimensions=OLD_SIZE,
        index_version=settings.document_index_version,
        question="leave?",
    )
    assert stored == [(old_key, result.vector)]
    assert len(result.vector) == OLD_SIZE and vi.provider.models()[-1] == OLD_MODEL


def test_reindex_while_failed_forgets_the_row_so_the_rebuild_rewrites_it(
    vi: VectorIndexEnv,
) -> None:
    gen = vi.adopt_and_register()
    seeded = vi.seed_indexed("during-build")
    chunks = vi.chunk_count(seeded)
    assert vi.generation_documents(gen.id) == {seeded.document_id: chunks}

    # The generation fails verification; dual writes stop while it is failed.
    vi.run(lifecycle_service.set_state(gen.id, state="failed", error_code="point_count_mismatch"))
    result = vi.process(seeded, "reindex-while-failed", force=True)
    assert result["status"] == "indexed"

    # Its points in the failed generation predate the new chunk rows: the row is gone.
    assert vi.generation_documents(gen.id) == {}

    vi.provider.calls.clear()
    progress = vi.build()
    assert progress.documents_written == 1 and progress.documents_skipped == 0
    assert set(vi.provider.models()) <= {NEW_MODEL}
    assert vi.generation_documents(gen.id) == {seeded.document_id: chunks}
    assert progress.verify is not None and progress.verify.passed


def test_delete_skips_a_generation_whose_collection_is_gone(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.workers.ingestion import deletion

    monkeypatch.setattr(deletion, "_delete_objects_by_prefix", lambda **_: 0)
    seeded = vi.seed_indexed("doc")
    gen = vi.adopt_and_register()
    vi.build()
    original = vi.client.delete

    def _delete(*, collection_name: str, **kwargs: Any) -> None:
        if collection_name == gen.collection_name:
            raise UnexpectedResponse(404, "Not Found", b"", {})  # type: ignore[arg-type]
        original(collection_name=collection_name, **kwargs)

    monkeypatch.setattr(vi.client, "delete", _delete)
    vi.delete(seeded)

    assert vi.points(settings.qdrant_collection, seeded) == {}


def test_delete_with_an_explicit_collection_still_raises_on_404(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded = vi.seed_indexed("doc")

    def _delete(**_: Any) -> None:
        raise UnexpectedResponse(404, "Not Found", b"", {})  # type: ignore[arg-type]

    monkeypatch.setattr(vi.client, "delete", _delete)
    from app.workers import document_tasks

    with pytest.raises(UnexpectedResponse):
        vi.run(
            document_tasks._qdrant_service.delete_document_points(
                organization_id=seeded.organization_id,
                document_id=seeded.document_id,
                collection_name="rudix_missing_collection",
            )
        )


def test_cache_with_a_duck_typed_service_embeds_without_pinning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    class _Service:
        embedding_model = "duck-model"
        vector_size = 2

        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def embed_query(self, **kwargs: Any) -> tuple[list[float], int]:
            self.calls.append(kwargs)
            return [0.5, 0.5], 4

    async def _get_or_load(*, loader: Any, **_: Any) -> Any:
        return await loader()

    monkeypatch.setattr(query_embedding_cache, "get_or_load", _get_or_load)
    service = _Service()
    result = asyncio.run(
        embed_query_cached(service, organization_id=uuid4(), question="q?")  # type: ignore[arg-type]
    )
    assert result.vector == [0.5, 0.5] and result.prompt_tokens == 4
    assert service.calls == [{"question": "q?"}]


def test_index_stage_without_generation_targets_records_nothing() -> None:
    import asyncio
    from types import SimpleNamespace

    from app.workers.ingestion.stages import embed_generations

    ctx = SimpleNamespace(metrics={})
    recorded = asyncio.run(
        embed_generations.record_generation_documents(
            ctx,  # type: ignore[arg-type]
            SimpleNamespace(id=uuid4()),
            cleanup=lambda _: asyncio.sleep(0, result=0),
        )
    )
    assert recorded == 0
