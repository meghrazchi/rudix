from __future__ import annotations

import os
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from qdrant_client.http.models import MatchAny, MatchValue

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

from app.core.config import settings
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService


class FakeEmbeddingsEndpoint:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create(self, *, model: str, input: list[str]) -> object:
        self.calls.append({"model": model, "input": input})
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.01] * settings.qdrant_vector_size)],
            usage=SimpleNamespace(prompt_tokens=11),
        )


class FakeOpenAIClient:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddingsEndpoint()


@dataclass(frozen=True)
class FakeQdrantResult:
    score: float
    payload: dict[str, object]


class FakeQdrantClient:
    def __init__(self, *, results: list[FakeQdrantResult]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    def search(self, **kwargs: object) -> list[FakeQdrantResult]:
        self.calls.append(kwargs)
        return list(self.results)


class FakeQdrantQueryPointsClient:
    def __init__(self, *, results: list[FakeQdrantResult]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    def query_points(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(points=list(self.results))


@pytest.mark.asyncio
async def test_embed_query_uses_configured_embedding_model() -> None:
    fake_openai = FakeOpenAIClient()
    service = QueryRetrievalService(
        embedding_model="text-embedding-3-small",
        openai_client=fake_openai,
    )

    vector, prompt_tokens = await service.embed_query(question="How many leave days?")

    assert len(vector) == settings.qdrant_vector_size
    assert prompt_tokens == 11
    assert len(fake_openai.embeddings.calls) == 1
    assert fake_openai.embeddings.calls[0]["model"] == "text-embedding-3-small"
    assert fake_openai.embeddings.calls[0]["input"] == ["How many leave days?"]


def test_retrieve_candidates_applies_org_and_document_filters() -> None:
    organization_id = uuid4()
    allowed_document_ids = [uuid4(), uuid4()]
    chunk_id = uuid4()
    fake_qdrant = FakeQdrantClient(
        results=[
            FakeQdrantResult(
                score=0.91,
                payload={
                    "organization_id": str(organization_id),
                    "document_id": str(allowed_document_ids[0]),
                    "chunk_id": str(chunk_id),
                    "filename": "policy.pdf",
                    "page_number": 4,
                    "text": "Employees receive twenty days of annual leave.",
                },
            )
        ]
    )
    service = QueryRetrievalService(qdrant_client=fake_qdrant)

    candidates = service.retrieve_candidates(
        query_vector=[0.01] * settings.qdrant_vector_size,
        organization_id=organization_id,
        document_ids=allowed_document_ids,
        initial_top_k=10,
    )

    assert len(candidates) == 1
    assert candidates[0].document_id == allowed_document_ids[0]
    assert candidates[0].chunk_id == chunk_id
    assert candidates[0].filename == "policy.pdf"
    assert candidates[0].page_number == 4
    assert candidates[0].similarity_score == pytest.approx(0.91)

    assert len(fake_qdrant.calls) == 1
    query_filter = fake_qdrant.calls[0]["query_filter"]
    assert query_filter.must is not None
    assert len(query_filter.must) == 2
    assert query_filter.must[0].key == "organization_id"
    assert isinstance(query_filter.must[0].match, MatchValue)
    assert query_filter.must[0].match.value == str(organization_id)
    assert query_filter.must[1].key == "document_id"
    assert isinstance(query_filter.must[1].match, MatchAny)
    assert query_filter.must[1].match.any == [str(allowed_document_ids[0]), str(allowed_document_ids[1])]


def test_retrieve_candidates_drops_cross_org_and_unauthorized_documents() -> None:
    organization_id = uuid4()
    allowed_document_id = uuid4()
    unauthorized_document_id = uuid4()

    fake_qdrant = FakeQdrantClient(
        results=[
            FakeQdrantResult(
                score=0.90,
                payload={
                    "organization_id": str(organization_id),
                    "document_id": str(allowed_document_id),
                    "chunk_id": str(uuid4()),
                    "filename": "allowed.pdf",
                    "page_number": 1,
                    "text": "Authorized content",
                },
            ),
            FakeQdrantResult(
                score=0.99,
                payload={
                    "organization_id": str(uuid4()),
                    "document_id": str(allowed_document_id),
                    "chunk_id": str(uuid4()),
                    "filename": "foreign-org.pdf",
                    "page_number": 2,
                    "text": "Foreign organization content",
                },
            ),
            FakeQdrantResult(
                score=0.98,
                payload={
                    "organization_id": str(organization_id),
                    "document_id": str(unauthorized_document_id),
                    "chunk_id": str(uuid4()),
                    "filename": "foreign-doc.pdf",
                    "page_number": 3,
                    "text": "Unauthorized document content",
                },
            ),
        ]
    )
    service = QueryRetrievalService(qdrant_client=fake_qdrant)

    candidates = service.retrieve_candidates(
        query_vector=[0.01] * settings.qdrant_vector_size,
        organization_id=organization_id,
        document_ids=[allowed_document_id],
        initial_top_k=20,
    )

    assert len(candidates) == 1
    assert candidates[0].document_id == allowed_document_id
    assert candidates[0].filename == "allowed.pdf"


def test_retrieve_candidates_supports_query_points_client() -> None:
    organization_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    fake_qdrant = FakeQdrantQueryPointsClient(
        results=[
            FakeQdrantResult(
                score=0.77,
                payload={
                    "organization_id": str(organization_id),
                    "document_id": str(document_id),
                    "chunk_id": str(chunk_id),
                    "filename": "query-points.pdf",
                    "page_number": 6,
                    "text": "Retrieved by query_points.",
                },
            )
        ]
    )
    service = QueryRetrievalService(qdrant_client=fake_qdrant)

    candidates = service.retrieve_candidates(
        query_vector=[0.01] * settings.qdrant_vector_size,
        organization_id=organization_id,
        document_ids=[document_id],
        initial_top_k=20,
    )

    assert len(candidates) == 1
    assert candidates[0].document_id == document_id
    assert candidates[0].chunk_id == chunk_id
    assert candidates[0].similarity_score == pytest.approx(0.77)
    assert len(fake_qdrant.calls) == 1
    assert "query" in fake_qdrant.calls[0]


@pytest.mark.asyncio
async def test_embed_and_retrieve_returns_required_citation_metadata() -> None:
    organization_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    fake_openai = FakeOpenAIClient()
    fake_qdrant = FakeQdrantClient(
        results=[
            FakeQdrantResult(
                score=0.87,
                payload={
                    "organization_id": str(organization_id),
                    "document_id": str(document_id),
                    "chunk_id": str(chunk_id),
                    "filename": "benefits.pdf",
                    "page_number": 8,
                    "text": "Benefits policy details.",
                },
            )
        ]
    )
    service = QueryRetrievalService(
        openai_client=fake_openai,
        qdrant_client=fake_qdrant,
    )

    result = await service.embed_and_retrieve(
        question="What benefits are documented?",
        organization_id=organization_id,
        document_ids=[document_id],
        initial_top_k=5,
    )

    assert result.embedding_model == settings.openai_embedding_model
    assert result.embedding_prompt_tokens == 11
    assert len(result.query_vector) == settings.qdrant_vector_size
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.document_id == document_id
    assert candidate.chunk_id == chunk_id
    assert candidate.filename == "benefits.pdf"
    assert candidate.page_number == 8
    assert candidate.text == "Benefits policy details."
    assert candidate.similarity_score == pytest.approx(0.87)
