import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

# Ensure strict settings can be loaded when importing modules in tests.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.services.qdrant_service import QdrantService


@dataclass
class ChunkStub:
    id: UUID
    document_id: UUID
    page_number: int | None
    chunk_index: int
    text: str
    token_count: int
    qdrant_point_id: str | None
    embedding_model: str
    index_version: str


class FakeQdrantClient:
    def __init__(self) -> None:
        self.upsert_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.storage: dict[str, dict[str, object]] = {}

    def upsert(self, *, collection_name: str, points: list[object], wait: bool) -> None:
        self.upsert_calls.append(
            {
                "collection_name": collection_name,
                "points": points,
                "wait": wait,
            }
        )
        for point in points:
            point_id = str(point.id)
            self.storage[point_id] = {
                "vector": list(point.vector),
                "payload": dict(point.payload or {}),
            }

    def delete(self, *, collection_name: str, points_selector: object, wait: bool) -> None:
        self.delete_calls.append(
            {
                "collection_name": collection_name,
                "points_selector": points_selector,
                "wait": wait,
            }
        )


@pytest.mark.asyncio
async def test_upsert_chunks_includes_required_payload_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeQdrantClient()
    ensure_calls = {"count": 0}

    monkeypatch.setattr(qdrant_module, "qdrant_client", fake_client)
    monkeypatch.setattr(
        qdrant_module,
        "ensure_qdrant_collection",
        lambda: ensure_calls.__setitem__("count", ensure_calls["count"] + 1),
    )

    service = QdrantService(batch_size=64)
    document_id = uuid4()
    organization_id = uuid4()
    user_id = uuid4()
    chunk_id = uuid4()

    chunk = ChunkStub(
        id=chunk_id,
        document_id=document_id,
        page_number=2,
        chunk_index=7,
        text="policy text",
        token_count=123,
        qdrant_point_id=service.build_point_id(
            document_id=document_id,
            chunk_index=7,
            index_version="v1",
        ),
        embedding_model="text-embedding-3-small",
        index_version="v1",
    )
    vectors = {chunk_id: [0.001] * settings.qdrant_vector_size}

    result = await service.upsert_chunks(
        organization_id=organization_id,
        user_id=user_id,
        document_id=document_id,
        filename="policy.pdf",
        file_type="pdf",
        chunks=[chunk],
        vectors_by_chunk_id=vectors,
    )

    assert ensure_calls["count"] == 1
    assert result.upserted_count == 1
    assert result.batch_count == 1
    assert result.point_ids_by_chunk_id == {chunk_id: chunk.qdrant_point_id}

    assert len(fake_client.upsert_calls) == 1
    upsert_call = fake_client.upsert_calls[0]
    assert upsert_call["collection_name"] == settings.qdrant_collection
    assert upsert_call["wait"] is True

    points = upsert_call["points"]
    assert isinstance(points, list)
    assert len(points) == 1
    payload = points[0].payload

    assert payload["organization_id"] == str(organization_id)
    assert payload["user_id"] == str(user_id)
    assert payload["document_id"] == str(document_id)
    assert payload["chunk_id"] == str(chunk_id)
    assert payload["filename"] == "policy.pdf"
    assert payload["file_type"] == "pdf"
    assert payload["page_number"] == 2
    assert payload["chunk_index"] == 7
    assert payload["text"] == "policy text"
    assert payload["embedding_model"] == "text-embedding-3-small"
    assert payload["index_version"] == "v1"


@pytest.mark.asyncio
async def test_upsert_chunks_is_idempotent_for_same_point_id(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeQdrantClient()
    monkeypatch.setattr(qdrant_module, "qdrant_client", fake_client)
    monkeypatch.setattr(qdrant_module, "ensure_qdrant_collection", lambda: None)

    service = QdrantService(batch_size=2)
    document_id = uuid4()
    chunk_id = uuid4()
    point_id = service.build_point_id(document_id=document_id, chunk_index=0, index_version="v1")

    chunk = ChunkStub(
        id=chunk_id,
        document_id=document_id,
        page_number=1,
        chunk_index=0,
        text="first text",
        token_count=50,
        qdrant_point_id=point_id,
        embedding_model="text-embedding-3-small",
        index_version="v1",
    )
    vectors = {chunk_id: [0.002] * settings.qdrant_vector_size}

    await service.upsert_chunks(
        organization_id=uuid4(),
        user_id=uuid4(),
        document_id=document_id,
        filename="doc.txt",
        file_type="txt",
        chunks=[chunk],
        vectors_by_chunk_id=vectors,
    )

    # Same point id, different payload/text: qdrant upsert should overwrite in-place.
    chunk_v2 = ChunkStub(
        id=chunk_id,
        document_id=document_id,
        page_number=1,
        chunk_index=0,
        text="second text",
        token_count=60,
        qdrant_point_id=point_id,
        embedding_model="text-embedding-3-small",
        index_version="v1",
    )
    await service.upsert_chunks(
        organization_id=uuid4(),
        user_id=uuid4(),
        document_id=document_id,
        filename="doc.txt",
        file_type="txt",
        chunks=[chunk_v2],
        vectors_by_chunk_id=vectors,
    )

    assert len(fake_client.storage) == 1
    stored = fake_client.storage[point_id]
    assert stored["payload"]["text"] == "second text"
    assert stored["payload"]["token_count"] == 60


def test_build_point_id_is_deterministic() -> None:
    service = QdrantService()
    document_id = uuid4()

    first = service.build_point_id(document_id=document_id, chunk_index=4, index_version="v2")
    second = service.build_point_id(document_id=document_id, chunk_index=4, index_version="v2")
    different = service.build_point_id(document_id=document_id, chunk_index=5, index_version="v2")

    assert first == second
    assert different != first
    assert first == f"{document_id}:v2:4"


@pytest.mark.asyncio
async def test_delete_document_points_uses_org_and_document_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeQdrantClient()
    ensure_calls = {"count": 0}

    monkeypatch.setattr(qdrant_module, "qdrant_client", fake_client)
    monkeypatch.setattr(
        qdrant_module,
        "ensure_qdrant_collection",
        lambda: ensure_calls.__setitem__("count", ensure_calls["count"] + 1),
    )

    service = QdrantService()
    organization_id = uuid4()
    document_id = uuid4()
    result = await service.delete_document_points(
        organization_id=organization_id,
        document_id=document_id,
    )

    assert result.deleted is True
    assert ensure_calls["count"] == 1
    assert len(fake_client.delete_calls) == 1

    delete_call = fake_client.delete_calls[0]
    assert delete_call["collection_name"] == settings.qdrant_collection
    assert delete_call["wait"] is True
    selector = delete_call["points_selector"]
    must_conditions = getattr(selector, "must", None)
    assert isinstance(must_conditions, list)
    assert len(must_conditions) == 2
    condition_map = {
        condition.key: condition.match.value
        for condition in must_conditions
    }
    assert condition_map["organization_id"] == str(organization_id)
    assert condition_map["document_id"] == str(document_id)


@pytest.mark.asyncio
async def test_delete_document_points_can_scope_to_index_version(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeQdrantClient()
    monkeypatch.setattr(qdrant_module, "qdrant_client", fake_client)
    monkeypatch.setattr(qdrant_module, "ensure_qdrant_collection", lambda: None)

    service = QdrantService()
    organization_id = uuid4()
    document_id = uuid4()
    await service.delete_document_points(
        organization_id=organization_id,
        document_id=document_id,
        index_version="v-next",
    )

    assert len(fake_client.delete_calls) == 1
    selector = fake_client.delete_calls[0]["points_selector"]
    must_conditions = getattr(selector, "must", None)
    assert isinstance(must_conditions, list)
    assert len(must_conditions) == 3
    condition_map = {
        condition.key: condition.match.value
        for condition in must_conditions
    }
    assert condition_map["organization_id"] == str(organization_id)
    assert condition_map["document_id"] == str(document_id)
    assert condition_map["index_version"] == "v-next"
