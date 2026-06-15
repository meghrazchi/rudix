"""Unit tests for ConflictDetectionService (F301)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
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

from app.domains.chat.services.conflict_detection_service import (
    ConflictDetectionChunk,
    ConflictDetectionResult,
    ConflictDetectionService,
    _ConflictDetectorOutput,
)


@dataclass
class _FakeResponse:
    content: str
    model: str = "gpt-5.4-mini"


def _make_service() -> ConflictDetectionService:
    return ConflictDetectionService(timeout_seconds=5.0)


def _mock_provider(response_json: str) -> AsyncMock:
    provider = AsyncMock()
    provider.complete.return_value = _FakeResponse(content=response_json)
    return provider


def _make_chunks() -> list[ConflictDetectionChunk]:
    return [
        ConflictDetectionChunk(
            chunk_id="chunk-a-1",
            document_id="doc-a",
            text="Policy A says annual leave is 20 days and effective May 1.",
            similarity_score=0.91,
            trust_status="verified",
        ),
        ConflictDetectionChunk(
            chunk_id="chunk-b-1",
            document_id="doc-b",
            text="Policy B says annual leave is 30 days and effective June 1.",
            similarity_score=0.88,
            trust_status="current",
        ),
    ]


_CONFLICT_JSON = """{
  "agreement_level": "conflicting",
  "conflict_pairs": [
    {
      "doc_label_a": "DOC_1",
      "doc_label_b": "DOC_2",
      "topic": "annual leave allowance",
      "severity": "high"
    }
  ],
  "conflict_summary": "Two documents disagree on annual leave allowance.",
  "preferred_doc_labels": ["DOC_2"]
}"""


class TestConflictDetectorSchema:
    def test_schema_parses_valid_conflict_output(self) -> None:
        output = _ConflictDetectorOutput.model_validate(
            {
                "agreement_level": "conflicting",
                "conflict_pairs": [
                    {
                        "doc_label_a": "DOC_1",
                        "doc_label_b": "DOC_2",
                        "topic": "effective date",
                        "severity": "high",
                    }
                ],
                "conflict_summary": "Documents disagree on the effective date.",
                "preferred_doc_labels": ["DOC_1"],
            }
        )
        assert output.agreement_level == "conflicting"
        assert len(output.conflict_pairs) == 1
        assert output.preferred_doc_labels == ["DOC_1"]


class TestConflictDetectorService:
    @pytest.mark.asyncio
    async def test_detect_skips_when_fewer_than_two_documents(self) -> None:
        svc = _make_service()
        result = await svc.detect(
            chunks=[
                ConflictDetectionChunk(
                    chunk_id="chunk-a-1",
                    document_id="doc-a",
                    text="Single-source answer.",
                    similarity_score=0.9,
                    trust_status="current",
                )
            ],
            min_source_docs=2,
        )
        assert result == ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="full",
            applied=False,
        )

    @pytest.mark.asyncio
    async def test_detect_prefers_trusted_source_over_llm_hint(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_CONFLICT_JSON)
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=_make_chunks(), min_source_docs=2)

        assert result.applied is True
        assert result.conflict_detected is True
        assert result.agreement_level == "conflicting"
        assert result.conflict_summary == "Two documents disagree on annual leave allowance."
        assert len(result.conflict_pairs) == 1
        assert result.conflict_pairs[0].severity == "high"
        assert result.preferred_document_ids == ["doc-a"]
        assert set(result.conflicting_document_ids) == {"doc-a", "doc-b"}

    @pytest.mark.asyncio
    async def test_detect_falls_back_on_invalid_json(self) -> None:
        svc = _make_service()
        provider = _mock_provider("not json")
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=_make_chunks(), min_source_docs=2)

        assert result.conflict_detected is False
        assert result.applied is False
        assert result.agreement_level == "full"
        assert result.conflict_summary == ""
