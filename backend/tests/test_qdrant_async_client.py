"""AsyncQdrantClient on the request and write paths (R06-07).

Counting fakes check the round trips: an upsert is one call per batch with no collection
or payload-index call, a delete one call, searches use the short-timeout client and
writes the long one, and parent text resolved from Postgres equals the payload copy.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
)
from inmemory_qdrant import AsyncInMemoryQdrant, InMemoryQdrant, text_vector
from qdrant_client.http.exceptions import UnexpectedResponse

from app.application.chat.pipeline import request_helpers
from app.clients import factory, qdrant_bootstrap
from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.documents.services.embedding_service import EmbeddingService
from app.domains.documents.services.qdrant_service import QdrantService
from app.workers import celery_app, document_tasks

HIERARCHICAL = {"strategy": "hierarchical", "chunk_size_tokens": 30, "chunk_overlap_tokens": 5}
TEXT = (
    "# Leave\n\nEmployees receive twenty days of paid annual leave each year. Requests go "
    "through the people portal two weeks in advance. Up to five unused days carry over.\n\n"
    "# Travel\n\nBusiness travel is booked through the travel desk. Economy class applies to "
    "flights under six hours and premium economy applies to longer flights."
)


class _Chunk:
    def __init__(self, index: int, document_id: UUID) -> None:
        self.id = uuid4()
        self.document_id = document_id
        self.page_number = 1
        self.chunk_index = index
        self.text = f"text {index}"
        self.token_count = 3
        self.qdrant_point_id = None
        self.embedding_model = "m"
        self.index_version = "v1"
        self.chunk_hash = f"h{index}"
        self.section_path = None
        self.language = None
        self.chunk_level = None
        self.parent_chunk_id = None
        self.child_count = None
        self.chunk_type = "text"
        self.table_metadata = None


@pytest.fixture
def async_write(monkeypatch: pytest.MonkeyPatch) -> AsyncInMemoryQdrant:
    client = AsyncInMemoryQdrant()
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(qdrant_module, "get_async_write_client", lambda: client)
    return client


async def test_upsert_is_one_round_trip_per_batch(async_write: AsyncInMemoryQdrant) -> None:
    service = QdrantService(batch_size=2)
    document_id = uuid4()
    chunks = [_Chunk(i, document_id) for i in range(5)]
    result = await service.upsert_chunks(
        organization_id=uuid4(),
        user_id=uuid4(),
        document_id=document_id,
        filename="a.txt",
        file_type="txt",
        chunks=chunks,  # type: ignore[arg-type]
        vectors_by_chunk_id={c.id: [0.0] * settings.qdrant_vector_size for c in chunks},
        ingest_run_id="run-1",
    )
    assert result.batch_count == 3
    assert dict(async_write.calls) == {"upsert": 3}
    payloads = [p.payload for p in async_write.points(settings.qdrant_collection).values()]
    assert {p["ingest_run_id"] for p in payloads} == {"run-1"}
    assert all("parent_text" in p for p in payloads)


async def test_delete_is_one_call(async_write: AsyncInMemoryQdrant) -> None:
    await QdrantService().delete_document_points(organization_id=uuid4(), document_id=uuid4())
    assert dict(async_write.calls) == {"delete": 1}


async def test_payload_omits_parent_text_when_not_stored(
    async_write: AsyncInMemoryQdrant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "qdrant_store_parent_text", False)
    chunk = _Chunk(0, uuid4())
    await QdrantService().upsert_chunks(
        organization_id=uuid4(),
        user_id=uuid4(),
        document_id=chunk.document_id,
        filename="a.txt",
        file_type="txt",
        chunks=[chunk],  # type: ignore[list-item]
        vectors_by_chunk_id={chunk.id: [0.0] * settings.qdrant_vector_size},
        parent_text_by_chunk_id={chunk.id: "parent"},
    )
    (point,) = async_write.points(settings.qdrant_collection).values()
    assert "parent_text" not in point.payload and "ingest_run_id" not in point.payload


class _MissingOnce(AsyncInMemoryQdrant):
    def __init__(self, status: int) -> None:
        super().__init__()
        self.status = status

    async def delete(self, **kwargs: Any) -> None:  # type: ignore[override]
        if self.status:
            status, self.status = self.status, 0
            raise UnexpectedResponse(status, "Not Found", b"", None)  # type: ignore[arg-type]
        await super().delete(**kwargs)


@pytest.mark.parametrize(
    ("status", "bootstrap_ok", "raises"),
    [(404, True, False), (404, False, True), (500, True, True)],
)
async def test_missing_collection_is_bootstrapped_once(
    monkeypatch: pytest.MonkeyPatch, status: int, bootstrap_ok: bool, raises: bool
) -> None:
    client = _MissingOnce(status)
    boots: list[bool] = []
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(qdrant_module, "get_async_write_client", lambda: client)
    monkeypatch.setattr(qdrant_bootstrap, "bootstrap", lambda: boots.append(True) or bootstrap_ok)
    call = QdrantService().delete_document_points(organization_id=uuid4(), document_id=uuid4())
    if raises:
        with pytest.raises(UnexpectedResponse):
            await call
    else:
        await call
        assert client.calls["delete"] == 1
    assert len(boots) == (1 if status == 404 else 0)


async def test_search_uses_the_short_and_writes_the_long_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, float]] = []

    class _Recorder(AsyncInMemoryQdrant):
        def __init__(self, timeout: float) -> None:
            super().__init__()
            self.timeout = timeout

    def _create(config: Any, *, timeout_seconds: float) -> _Recorder:
        created.append(("client", timeout_seconds))
        return _Recorder(timeout_seconds)

    monkeypatch.setattr(qdrant_module, "create_async_qdrant_client", _create)
    monkeypatch.setattr(qdrant_module, "_async_clients", {})
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(settings, "qdrant_timeout_seconds", 2.0)
    monkeypatch.setattr(settings, "qdrant_search_timeout_seconds", None)
    monkeypatch.setattr(settings, "qdrant_write_timeout_seconds", 30.0)

    search = qdrant_module.get_async_search_client()
    write = qdrant_module.get_async_write_client()
    assert search is qdrant_module.get_async_search_client()  # one per loop
    assert search.timeout == 2.0 and write.timeout == 30.0  # type: ignore[attr-defined]
    assert request_helpers._get_qdrant_client() is search

    org = uuid4()
    point = type(
        "P",
        (),
        {
            "id": "1",
            "vector": [0.0],
            "payload": {
                "organization_id": str(org),
                "document_id": str(uuid4()),
                "chunk_id": str(uuid4()),
                "filename": "a.txt",
                "text": "hello",
            },
        },
    )()
    await write.upsert(collection_name=settings.qdrant_collection, points=[point])
    search.collections = write.collections
    candidates = await QueryRetrievalService().aretrieve_candidates(
        query_vector=[0.0], organization_id=org, document_ids=None, initial_top_k=3
    )
    assert [c.text for c in candidates] == ["hello"]
    assert search.calls["query_points"] == 1 and write.calls["query_points"] == 0

    monkeypatch.setattr(settings, "qdrant_search_timeout_seconds", 0.5)
    assert qdrant_module.search_timeout_seconds() == 0.5
    await qdrant_module.close_async_qdrant_clients()
    assert search.calls["close"] == 1 and write.calls["close"] == 1
    assert qdrant_module._async_clients == {}


def test_async_clients_are_per_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        qdrant_module,
        "create_async_qdrant_client",
        lambda config, *, timeout_seconds: AsyncInMemoryQdrant(),
    )
    monkeypatch.setattr(qdrant_module, "_async_clients", {})

    async def _get() -> Any:
        return qdrant_module.get_async_write_client()

    first_loop = asyncio.new_event_loop()
    first = first_loop.run_until_complete(_get())
    first_loop.close()
    second_loop = asyncio.new_event_loop()
    try:
        second = second_loop.run_until_complete(_get())
        assert second is not first
        assert len(qdrant_module._async_clients) == 1  # the closed loop's entry was dropped
    finally:
        second_loop.close()


def test_factory_builds_an_async_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(factory, "AsyncQdrantClient", _Client)
    factory.create_async_qdrant_client(settings, timeout_seconds=29.6)
    assert seen["timeout"] == 30 and seen["url"] == str(settings.qdrant_url)


def test_injected_sync_client_and_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    created = InMemoryQdrant()
    created.get_collections = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr(qdrant_module, "create_qdrant_client", lambda _settings: created)
    monkeypatch.setattr(settings, "qdrant_bootstrap_collection", False)
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(qdrant_module, "_initialized_client", None)
    qdrant_module.init_qdrant()
    assert qdrant_module.injected_sync_client() is None  # created by init_qdrant
    other = InMemoryQdrant()
    monkeypatch.setattr(qdrant_module, "qdrant_client", other)
    assert qdrant_module.injected_sync_client() is other
    assert request_helpers._get_qdrant_client() is other

    ensured: list[bool] = []
    monkeypatch.setattr(qdrant_module, "ensure_qdrant_collection", lambda: ensured.append(True))
    assert qdrant_bootstrap.main() == 0 and ensured == [True]

    def _fail() -> None:
        raise RuntimeError("down")

    monkeypatch.setattr(qdrant_module, "ensure_qdrant_collection", _fail)
    assert qdrant_bootstrap.main() == 1


def test_worker_process_bootstrap_and_shutdown_never_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _init() -> None:
        calls.append("init")
        raise RuntimeError("qdrant down")

    async def _close_async() -> None:
        calls.append("close_async")

    monkeypatch.setattr(qdrant_module, "init_qdrant", _init)
    monkeypatch.setattr(qdrant_module, "close_async_qdrant_clients", _close_async)
    monkeypatch.setattr(qdrant_module, "close_qdrant", lambda: calls.append("close"))
    celery_app._bootstrap_qdrant()
    celery_app._shutdown_worker()

    def _broken() -> None:
        raise RuntimeError("closed")

    monkeypatch.setattr(qdrant_module, "close_qdrant", _broken)
    celery_app._shutdown_worker()
    assert calls[:3] == ["init", "close_async", "close"]


class _Provider:
    async def embed(self, request: Any) -> Any:
        from app.domains.ai.providers.protocols import EmbeddingResponse

        return EmbeddingResponse(
            vectors=[text_vector(t, settings.qdrant_vector_size) for t in request.texts],
            model=request.model,
            prompt_tokens=1,
            total_tokens=1,
            latency_ms=1,
        )


def test_parent_text_is_identical_with_the_setting_on_and_off(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ingestion_env
    client = InMemoryQdrant()
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    monkeypatch.setattr(document_tasks, "_qdrant_service", QdrantService())
    monkeypatch.setattr(
        document_tasks,
        "_embedding_service",
        EmbeddingService(provider=_Provider(), model_name=settings.openai_embedding_model),
    )
    env.set_content(TEXT.encode())
    results: dict[bool, list[tuple[str, str | None]]] = {}
    for stored in (True, False):
        monkeypatch.setattr(settings, "qdrant_store_parent_text", stored)
        seeded = env.seed()
        env.run_task(
            document_tasks.process_document,
            seeded.document_id,
            task_id=f"parents-{stored}",
            chunking_profile_config=HIERARCHICAL,
            organization_id=str(seeded.organization_id),
            user_id=str(seeded.user_id),
        )
        payloads = [
            p.payload
            for p in client.points(settings.qdrant_collection).values()
            if p.payload["document_id"] == str(seeded.document_id)
        ]
        assert payloads and all(("parent_text" in p) is stored for p in payloads)
        service = QueryRetrievalService(session_factory=env.factory)
        candidates = env.run_async(
            service.aretrieve_candidates(
                query_vector=[0.0],
                organization_id=seeded.organization_id,
                document_ids=None,
                initial_top_k=50,
                qdrant_client=client,  # type: ignore[arg-type]
            )
        )
        results[stored] = sorted((c.text, c.parent_text) for c in candidates)
        if not stored:
            # A parent of another organisation is never read.
            other = env.run_async(service.resolve_parent_texts(candidates, organization_id=uuid4()))
            assert other == candidates
    assert results[True] == results[False]
    assert any(parent for _, parent in results[True])
