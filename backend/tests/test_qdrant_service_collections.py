"""QdrantService write target seam: optional collection_name (R06-01, contract 4.2.6)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from test_qdrant_service import ChunkStub, FakeQdrantClient

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.documents.services.qdrant_service import QdrantService, resolve_write_targets


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeQdrantClient:
    client = FakeQdrantClient()
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    monkeypatch.setattr(qdrant_module, "ensure_qdrant_collection", lambda: None)
    return client


def test_write_targets_default_to_the_configured_collection() -> None:
    assert resolve_write_targets() == [settings.qdrant_collection]


@pytest.mark.parametrize("collection", [None, "eval_collection"])
async def test_upsert_and_delete_use_the_given_collection(
    fake_client: FakeQdrantClient, collection: str | None
) -> None:
    service = QdrantService()
    document_id = uuid4()
    chunk = ChunkStub(
        id=uuid4(),
        document_id=document_id,
        page_number=1,
        chunk_index=0,
        text="text",
        token_count=1,
        qdrant_point_id=None,
        embedding_model="m",
        index_version="v1",
    )
    kwargs = {} if collection is None else {"collection_name": collection}
    await service.upsert_chunks(
        organization_id=uuid4(),
        user_id=uuid4(),
        document_id=document_id,
        filename="a.txt",
        file_type="txt",
        chunks=[chunk],  # type: ignore[list-item]
        vectors_by_chunk_id={chunk.id: [0.0] * settings.qdrant_vector_size},
        **kwargs,
    )
    await service.delete_document_points(
        organization_id=uuid4(), document_id=document_id, index_version="v1", **kwargs
    )
    expected = collection or settings.qdrant_collection
    assert fake_client.upsert_calls[0]["collection_name"] == expected
    assert fake_client.delete_calls[0]["collection_name"] == expected
