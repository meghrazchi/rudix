"""Embedding reuse, run markers, stale cleanup, and batch concurrency (R06-06).

The real ``QdrantService`` and ``EmbeddingService`` run against an in-memory Qdrant client
and a counting embedding provider, through the ingestion task bodies on SQLite.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    Seeded,
    ingestion_env,  # noqa: F401  (fixture)
)
from inmemory_qdrant import InMemoryQdrant, text_vector
from qdrant_client.http.models import FieldCondition
from sqlalchemy import select

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.ai.providers.errors import ProviderQuotaExceededError, retry_after_from_headers
from app.domains.ai.providers.protocols import EmbeddingRequest, EmbeddingResponse
from app.domains.documents.services.embedding_concurrency import ProviderPauseGate, run_bounded
from app.domains.documents.services.embedding_service import EmbeddingService
from app.domains.documents.services.qdrant_service import QdrantService
from app.models.document import DocumentChunk
from app.workers import document_tasks

SMALL_CHUNKS = {"strategy": "token_recursive", "chunk_size_tokens": 40, "chunk_overlap_tokens": 5}
PARAGRAPHS = [
    "Annual leave policy. Employees receive twenty days of paid annual leave each year. "
    "Requests are submitted through the people portal at least two weeks in advance.",
    "Carry over. Up to five unused days carry over into the first quarter of the next "
    "year. Days that are not used by the end of March expire without compensation.",
    "Sick leave. Sick leave is separate from annual leave and requires a medical note "
    "after three consecutive days. Managers record sick leave in the absence calendar.",
    "Travel. Business travel is booked through the travel desk. Economy class applies to "
    "flights under six hours and premium economy applies to longer flights.",
]
TEXT = "\n\n".join(PARAGRAPHS)


class CountingProvider:
    """Deterministic vectors; counts calls and the texts sent; tracks concurrency."""

    def __init__(self, *, delay: float = 0.0) -> None:
        self.calls: list[list[str]] = []
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0
        self.fail_first_with: Exception | None = None

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail_first_with is not None:
                error, self.fail_first_with = self.fail_first_with, None
                raise error
            self.calls.append(list(request.texts))
            return EmbeddingResponse(
                vectors=[text_vector(t, settings.qdrant_vector_size) for t in request.texts],
                model=request.model,
                prompt_tokens=len(request.texts),
                total_tokens=len(request.texts),
                latency_ms=1,
            )
        finally:
            self.in_flight -= 1

    @property
    def texts(self) -> list[str]:
        return [text for call in self.calls for text in call]


class VectorEnv:
    def __init__(self, env: IngestionEnv, client: InMemoryQdrant, provider: CountingProvider):
        self.env, self.client, self.provider = env, client, provider

    def ids(self, seeded: Seeded) -> dict[str, str]:
        return {"organization_id": str(seeded.organization_id), "user_id": str(seeded.user_id)}

    def process(self, seeded: Seeded, task_id: str) -> Any:
        return self.env.run_task(
            document_tasks.process_document,
            seeded.document_id,
            task_id=task_id,
            chunking_profile_config=SMALL_CHUNKS,
            **self.ids(seeded),
        )

    def reindex(self, seeded: Seeded, task_id: str) -> Any:
        return self.env.run_task(
            document_tasks.reindex_document,
            seeded.document_id,
            task_id=task_id,
            chunking_profile_config=SMALL_CHUNKS,
            **self.ids(seeded),
        )

    def points(self, seeded: Seeded) -> dict[int, tuple[str, list[float], str]]:
        return {
            int(p.payload["chunk_index"]): (p.id, p.vector, p.payload["text"])
            for p in self.client.points(settings.qdrant_collection).values()
            if p.payload["document_id"] == str(seeded.document_id)
        }

    def run_markers(self, seeded: Seeded) -> set[str]:
        return {
            p.payload["ingest_run_id"]
            for p in self.client.points(settings.qdrant_collection).values()
            if p.payload["document_id"] == str(seeded.document_id)
        }

    def chunk_texts(self, seeded: Seeded) -> list[str]:
        async def _read() -> list[str]:
            async with self.env.factory() as session:
                rows = await session.execute(
                    select(DocumentChunk.text)
                    .where(DocumentChunk.document_id == seeded.document_id)
                    .order_by(DocumentChunk.chunk_index)
                )
                return [str(text) for text in rows.scalars()]

        return self.env.run_async(_read())


@pytest.fixture
def vectors(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> VectorEnv:
    client = InMemoryQdrant()
    provider = CountingProvider()
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    monkeypatch.setattr(document_tasks, "_qdrant_service", QdrantService())
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        EmbeddingService(
            provider=provider, model_name=settings.openai_embedding_model, provider_type="fake"
        ),
    )
    return VectorEnv(ingestion_env, client, provider)


def test_reindex_of_an_unchanged_document_makes_no_embedding_calls(vectors: VectorEnv) -> None:
    vectors.env.set_content(TEXT.encode())
    seeded = vectors.env.seed()
    vectors.process(seeded, "first")
    first = vectors.points(seeded)
    assert len(first) > 2 and vectors.provider.calls
    first_markers = vectors.run_markers(seeded)

    vectors.provider.calls.clear()
    vectors.client.calls.clear()
    vectors.reindex(seeded, "second")

    assert vectors.provider.calls == []
    assert vectors.points(seeded) == first
    # Every point was rewritten by the reindex run (new marker), none is left behind.
    assert len(vectors.run_markers(seeded)) == 1
    assert vectors.run_markers(seeded) != first_markers
    assert vectors.client.calls["delete"] == 1 and vectors.client.calls["count"] == 1


def test_one_changed_chunk_is_the_only_one_embedded(vectors: VectorEnv) -> None:
    vectors.env.set_content(TEXT.encode())
    seeded = vectors.env.seed()
    vectors.process(seeded, "first")
    before = set(vectors.chunk_texts(seeded))

    changed = TEXT.replace("premium economy applies", "business class applies")
    vectors.env.set_content(changed.encode())
    vectors.provider.calls.clear()
    vectors.reindex(seeded, "second")

    after = vectors.chunk_texts(seeded)
    new_texts = [text for text in after if text not in before]
    assert len(new_texts) == 1
    assert vectors.provider.texts == new_texts
    stored = {text for _, _, text in vectors.points(seeded).values()}
    assert stored == set(after)


def test_reuse_never_crosses_organisations(vectors: VectorEnv) -> None:
    vectors.env.set_content(TEXT.encode())
    org_a = vectors.env.seed()
    vectors.process(org_a, "org-a")
    embedded_a = list(vectors.provider.texts)

    org_b = vectors.env.seed()
    assert org_b.organization_id != org_a.organization_id
    vectors.provider.calls.clear()
    vectors.client.filters.clear()
    vectors.process(org_b, "org-b")

    # Same text, other organisation: every chunk is embedded again.
    assert sorted(vectors.provider.texts) == sorted(embedded_a)
    scrolls = [flt for name, flt in vectors.client.filters if name == "scroll"]
    assert scrolls
    for flt in scrolls:
        conditions = {
            c.key: getattr(c.match, "value", None)
            for c in flt.must  # type: ignore[union-attr]
            if isinstance(c, FieldCondition)
        }
        assert conditions["organization_id"] == str(org_b.organization_id)
        assert conditions["embedding_model"] == settings.openai_embedding_model


def test_stale_points_of_a_longer_previous_version_are_deleted(vectors: VectorEnv) -> None:
    vectors.env.set_content((TEXT + "\n\n" + TEXT.replace("leave", "holiday")).encode())
    seeded = vectors.env.seed()
    vectors.process(seeded, "long")
    long_count = len(vectors.points(seeded))

    vectors.env.set_content(PARAGRAPHS[0].encode())
    vectors.reindex(seeded, "short")
    points = vectors.points(seeded)
    assert 0 < len(points) < long_count
    assert sorted(points) == list(range(len(points)))
    assert len(vectors.run_markers(seeded)) == 1


def test_concurrent_batches_match_sequential_batches(
    vectors: VectorEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ingest_embed_batch_chunks", 2)
    vectors.provider.delay = 0.1  # longer than one short session, so batches overlap
    vectors.env.set_content(TEXT.encode())
    results: dict[int, dict[int, tuple[list[float], str]]] = {}
    for limit in (1, 3):
        monkeypatch.setattr(settings, "embedding_max_concurrent_batches", limit)
        vectors.provider.max_in_flight = 0
        seeded = vectors.env.seed()  # a new organisation each time: no reuse
        vectors.process(seeded, f"limit-{limit}")
        results[limit] = {k: (v[1], v[2]) for k, v in vectors.points(seeded).items()}
        if limit == 3:
            assert vectors.provider.max_in_flight > 1
        else:
            assert vectors.provider.max_in_flight == 1
    assert len(results[1]) >= 4
    assert results[1] == results[3]


def test_point_count_mismatch_fails_the_index_stage(
    vectors: VectorEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _count(self: QdrantService, **_: Any) -> int:
        return 999

    monkeypatch.setattr(QdrantService, "count_document_points", _count)
    vectors.env.set_content(TEXT.encode())
    seeded = vectors.env.seed()
    with pytest.raises(Exception) as raised:
        vectors.env.run_async(
            document_tasks._extract_and_store_document_pages_async(str(seeded.document_id))
        )
    assert raised.value.error_details["code"] == "QDRANT_POINT_COUNT_MISMATCH"  # type: ignore[attr-defined]


def test_failed_reuse_lookup_embeds_the_batch(vectors: VectorEnv) -> None:
    def _broken(**_: Any) -> Any:
        raise RuntimeError("scroll failed")

    vectors.client.scroll = _broken  # type: ignore[method-assign]
    vectors.env.set_content(TEXT.encode())
    seeded = vectors.env.seed()
    vectors.process(seeded, "lookup-fails")
    assert len(vectors.provider.texts) == len(vectors.points(seeded))


async def test_find_reusable_vectors_checks_dimension_and_organisation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InMemoryQdrant()
    service = QdrantService()
    org = UUID(int=1)
    good = text_vector("a", settings.qdrant_vector_size)
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            type("P", (), {"id": "1", "vector": good, "payload": _payload(org, "h1")})(),
            type("P", (), {"id": "2", "vector": [0.1, 0.2], "payload": _payload(org, "h2")})(),
            type("P", (), {"id": "3", "vector": good, "payload": _payload(UUID(int=2), "h3")})(),
        ],
    )
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    found = await service.find_reusable_vectors(
        organization_id=org,
        embedding_model="m",
        chunk_hashes=["h1", "h2", "h3", None],
    )
    empty = await service.find_reusable_vectors(
        organization_id=org, embedding_model="m", chunk_hashes=[None]
    )
    assert found == {"h1": good}
    assert empty == {}
    assert client.calls["scroll"] == 1


def _store(client: InMemoryQdrant, org: UUID, rows: list[tuple[str, str]]) -> list[float]:
    vector = text_vector("dup", settings.qdrant_vector_size)
    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            type("P", (), {"id": pid, "vector": vector, "payload": _payload(org, h)})()
            for pid, h in rows
        ],
    )
    return vector


async def test_copies_of_one_text_do_not_crowd_out_other_hashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three copies of h1 fill a four-point page; one more scroll finds h2..h4."""
    client = InMemoryQdrant()
    org = UUID(int=1)
    copies = [("a1", "h1"), ("b1", "h1"), ("c1", "h1"), ("d1", "h1")]
    vector = _store(client, org, [*copies, ("d2", "h2"), ("d3", "h3"), ("d4", "h4")])
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    service = QdrantService()

    found = await service.find_reusable_vectors(
        organization_id=org, embedding_model="m", chunk_hashes=["h1", "h2", "h3", "h4"]
    )

    assert found == {"h1": vector, "h2": vector, "h3": vector, "h4": vector}
    assert client.calls["scroll"] == 2
    second = [flt for name, flt in client.filters if name == "scroll"][1]
    hashes = next(c.match.any for c in second.must if c.key == "chunk_hash")  # type: ignore[union-attr]
    assert sorted(hashes) == ["h2", "h3", "h4"]


async def test_reuse_lookup_scrolls_are_bounded_and_stop_without_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InMemoryQdrant()
    org = UUID(int=1)
    # A page that is not full means the missing hashes do not exist: one scroll.
    _store(client, org, [("x1", "h1")])
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    service = QdrantService()
    found = await service.find_reusable_vectors(
        organization_id=org, embedding_model="m", chunk_hashes=["h1", "h2"]
    )
    assert set(found) == {"h1"} and client.calls["scroll"] == 1

    # With one lookup allowed, the crowded page is not followed up.
    crowded = InMemoryQdrant()
    _store(crowded, org, [("a", "h1"), ("b", "h1"), ("c", "h2")])
    monkeypatch.setattr(qdrant_module, "qdrant_client", crowded)
    monkeypatch.setattr(settings, "embedding_reuse_max_lookups", 1)
    found = await service.find_reusable_vectors(
        organization_id=org, embedding_model="m", chunk_hashes=["h1", "h2"]
    )
    assert set(found) == {"h1"} and crowded.calls["scroll"] == 1

    # A full page of unusable hits (wrong dimension) finds nothing new: no further scroll.
    wrong = InMemoryQdrant()
    wrong.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            type("P", (), {"id": pid, "vector": [0.1], "payload": _payload(org, "h1")})()
            for pid in ("a", "b")
        ],
    )
    monkeypatch.setattr(qdrant_module, "qdrant_client", wrong)
    monkeypatch.setattr(settings, "embedding_reuse_max_lookups", 3)
    found = await service.find_reusable_vectors(
        organization_id=org, embedding_model="m", chunk_hashes=["h1", "h2"]
    )
    assert found == {} and wrong.calls["scroll"] == 1


def _payload(org: UUID, chunk_hash: str) -> dict[str, Any]:
    return {"organization_id": str(org), "embedding_model": "m", "chunk_hash": chunk_hash}


async def test_embed_chunks_concurrency_keeps_order_and_pauses_on_retry_after() -> None:
    provider = CountingProvider(delay=0.01)
    provider.fail_first_with = ProviderQuotaExceededError("slow down", retry_after_seconds=0.05)
    service = EmbeddingService(
        provider=provider,
        model_name="m",
        batch_max_items=1,
        max_concurrent_batches=3,
        retry_max_attempts=3,
    )
    chunks = [
        type("C", (), {"id": UUID(int=i), "text": f"t{i}", "token_count": 1})() for i in range(5)
    ]
    result = await service.embed_chunks(chunks=chunks)  # type: ignore[arg-type]
    assert list(result.vectors_by_chunk_id) == [c.id for c in chunks]
    for chunk in chunks:
        assert result.vectors_by_chunk_id[chunk.id] == text_vector(
            chunk.text, settings.qdrant_vector_size
        )
    assert service.pause_gate.pauses == 1
    assert result.retry_count == 1
    assert provider.max_in_flight > 1


async def test_pause_gate_and_bounded_runner() -> None:
    now = [100.0]
    gate = ProviderPauseGate(clock=lambda: now[0])
    assert gate.remaining() == 0
    assert gate.pause(1_000) == 60.0
    assert gate.remaining() == 60.0
    now[0] += 61
    await gate.wait()

    started: list[int] = []

    async def _ok(i: int) -> int:
        started.append(i)
        await asyncio.sleep(0)
        return i

    async def _fail() -> int:
        raise ValueError("boom")

    assert await run_bounded([lambda i=i: _ok(i) for i in range(4)], 2) == [0, 1, 2, 3]
    with pytest.raises(ValueError):
        await run_bounded([_fail, lambda: _ok(9)], 2)


def test_retry_after_header_parsing() -> None:
    assert retry_after_from_headers({"retry-after-ms": "250"}) == 0.25
    assert retry_after_from_headers({"retry-after": "3"}) == 3.0
    assert retry_after_from_headers({"retry-after": "Wed, 21 Oct"}) is None
    assert retry_after_from_headers(None) is None
    assert ProviderQuotaExceededError("x").retry_after_seconds is None
