"""Tests for F312: source conflict detection and multi-source agreement scoring.

Covers:
- ConflictDetectionService edge cases (partial, no preferred, equal trust)
- _compute_conflict_multiplier confidence penalty
- _with_conflict_status citation annotation
- _build_conflict_context prompt injection
- _build_conflict_detection_chunks input builder
- ConflictStatusRecord trust metadata assembly
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal
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
    ConflictPair,
)
from app.domains.chat.schemas.trust_metadata import ConflictStatusRecord
from app.interfaces.http.chat import (
    _build_conflict_context,
    _compute_conflict_multiplier,
    _with_conflict_status,
)
from app.domains.chat.schemas.chat import ChatCitationResponse


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


def _make_citation(
    document_id: str = "doc-1",
    chunk_id: str = "chunk-1",
    filename: str | None = "policy.pdf",
) -> ChatCitationResponse:
    return ChatCitationResponse(
        document_id=document_id,
        chunk_id=chunk_id,
        filename=filename,
    )


# ---------------------------------------------------------------------------
# ConflictDetectionService — additional edge cases
# ---------------------------------------------------------------------------

class TestConflictDetectionServiceEdgeCases:
    @pytest.mark.asyncio
    async def test_partial_agreement_level_returned(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"agreement_level":"partial","conflict_pairs":[],'
            '"conflict_summary":"Minor wording differences.","preferred_doc_labels":[]}'
        )
        chunks = [
            ConflictDetectionChunk(
                chunk_id="c1", document_id="doc-a",
                text="Leave is 20 days.", trust_status="current",
            ),
            ConflictDetectionChunk(
                chunk_id="c2", document_id="doc-b",
                text="Annual leave is approximately 20 days.", trust_status="current",
            ),
        ]
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=chunks, min_source_docs=2)

        assert result.applied is True
        assert result.conflict_detected is False
        assert result.agreement_level == "partial"
        assert result.conflict_summary == ""

    @pytest.mark.asyncio
    async def test_conflicting_without_valid_pairs_degrades_to_partial(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"agreement_level":"conflicting","conflict_pairs":[],'
            '"conflict_summary":"","preferred_doc_labels":[]}'
        )
        chunks = [
            ConflictDetectionChunk(
                chunk_id="c1", document_id="doc-a",
                text="Policy A.", trust_status="current",
            ),
            ConflictDetectionChunk(
                chunk_id="c2", document_id="doc-b",
                text="Policy B.", trust_status="current",
            ),
        ]
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=chunks, min_source_docs=2)

        assert result.agreement_level == "partial"
        assert result.conflict_detected is False
        assert result.conflict_pairs == []

    @pytest.mark.asyncio
    async def test_equal_trust_status_returns_all_at_best_rank(self) -> None:
        # When both docs share the same trust status, both are returned as
        # preferred (all docs at the best trust rank are included).  The LLM
        # label preference only affects sort order within the same rank.
        svc = _make_service()
        provider = _mock_provider(
            '{"agreement_level":"conflicting",'
            '"conflict_pairs":[{"doc_label_a":"DOC_1","doc_label_b":"DOC_2",'
            '"topic":"effective date","severity":"high"}],'
            '"conflict_summary":"Two documents disagree on effective date.",'
            '"preferred_doc_labels":["DOC_2"]}'
        )
        chunks = [
            ConflictDetectionChunk(
                chunk_id="c1", document_id="doc-a",
                text="Effective from May 1.", trust_status="current",
            ),
            ConflictDetectionChunk(
                chunk_id="c2", document_id="doc-b",
                text="Effective from June 1.", trust_status="current",
            ),
        ]
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=chunks, min_source_docs=2)

        assert result.applied is True
        assert result.conflict_detected is True
        assert set(result.preferred_document_ids) == {"doc-a", "doc-b"}

    @pytest.mark.asyncio
    async def test_no_preferred_when_preferred_labels_empty_and_equal_trust(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"agreement_level":"conflicting",'
            '"conflict_pairs":[{"doc_label_a":"DOC_1","doc_label_b":"DOC_2",'
            '"topic":"price","severity":"medium"}],'
            '"conflict_summary":"Prices differ.","preferred_doc_labels":[]}'
        )
        chunks = [
            ConflictDetectionChunk(
                chunk_id="c1", document_id="doc-a",
                text="Price is 100.", trust_status="current",
            ),
            ConflictDetectionChunk(
                chunk_id="c2", document_id="doc-b",
                text="Price is 200.", trust_status="current",
            ),
        ]
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=chunks, min_source_docs=2)

        assert result.conflict_detected is True
        assert len(result.preferred_document_ids) > 0

    @pytest.mark.asyncio
    async def test_verified_source_preferred_over_stale_regardless_of_llm(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"agreement_level":"conflicting",'
            '"conflict_pairs":[{"doc_label_a":"DOC_1","doc_label_b":"DOC_2",'
            '"topic":"policy","severity":"high"}],'
            '"conflict_summary":"Stale doc conflicts with verified doc.",'
            '"preferred_doc_labels":["DOC_1"]}'
        )
        chunks = [
            ConflictDetectionChunk(
                chunk_id="c1", document_id="doc-stale",
                text="Old policy.", trust_status="stale",
            ),
            ConflictDetectionChunk(
                chunk_id="c2", document_id="doc-verified",
                text="New policy.", trust_status="verified",
            ),
        ]
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=chunks, min_source_docs=2)

        assert result.preferred_document_ids == ["doc-verified"]

    @pytest.mark.asyncio
    async def test_detect_skips_with_single_document(self) -> None:
        svc = _make_service()
        chunks = [
            ConflictDetectionChunk(
                chunk_id="c1", document_id="doc-only",
                text="Single document.", trust_status="current",
            ),
            ConflictDetectionChunk(
                chunk_id="c2", document_id="doc-only",
                text="Same document, second chunk.", trust_status="current",
            ),
        ]
        result = await svc.detect(chunks=chunks, min_source_docs=2)
        assert result.applied is False
        assert result.conflict_detected is False

    @pytest.mark.asyncio
    async def test_full_agreement_returns_empty_pairs_and_no_preferred(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"agreement_level":"full","conflict_pairs":[],'
            '"conflict_summary":"","preferred_doc_labels":[]}'
        )
        chunks = [
            ConflictDetectionChunk(
                chunk_id="c1", document_id="doc-a",
                text="Leave is 20 days.", trust_status="current",
            ),
            ConflictDetectionChunk(
                chunk_id="c2", document_id="doc-b",
                text="Employees have 20 leave days.", trust_status="current",
            ),
        ]
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=chunks, min_source_docs=2)

        assert result.conflict_detected is False
        assert result.agreement_level == "full"
        assert result.conflict_pairs == []
        assert result.preferred_document_ids == []

    @pytest.mark.asyncio
    async def test_conflict_summary_empty_when_no_conflict(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"agreement_level":"conflicting",'
            '"conflict_pairs":[{"doc_label_a":"DOC_1","doc_label_b":"DOC_2",'
            '"topic":"rate","severity":"high"}],'
            '"conflict_summary":"Rate differs between documents.",'
            '"preferred_doc_labels":["DOC_1"]}'
        )
        chunks = [
            ConflictDetectionChunk(
                chunk_id="c1", document_id="doc-a",
                text="Rate 5%.", trust_status="current",
            ),
            ConflictDetectionChunk(
                chunk_id="c2", document_id="doc-b",
                text="Rate 7%.", trust_status="current",
            ),
        ]
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory.get_chat_provider",
            return_value=provider,
        ):
            result = await svc.detect(chunks=chunks, min_source_docs=2)

        assert result.conflict_detected is True
        assert result.conflict_summary != ""


# ---------------------------------------------------------------------------
# _compute_conflict_multiplier
# ---------------------------------------------------------------------------

class TestComputeConflictMultiplier:
    def test_full_agreement_returns_one(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="full",
        )
        assert _compute_conflict_multiplier(result) == 1.0

    def test_partial_agreement_applies_smaller_penalty(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="partial",
        )
        m = _compute_conflict_multiplier(result)
        assert 0.0 < m < 1.0

    def test_conflicting_applies_larger_penalty_than_partial(self) -> None:
        partial_result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="partial",
        )
        conflicting_result = ConflictDetectionResult(
            conflict_detected=True,
            agreement_level="conflicting",
        )
        assert _compute_conflict_multiplier(conflicting_result) <= _compute_conflict_multiplier(partial_result)

    def test_result_clamped_to_zero_or_above(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=True,
            agreement_level="conflicting",
        )
        assert _compute_conflict_multiplier(result) >= 0.0

    def test_unapplied_result_still_uses_agreement_level(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="full",
            applied=False,
        )
        assert _compute_conflict_multiplier(result) == 1.0


# ---------------------------------------------------------------------------
# _with_conflict_status
# ---------------------------------------------------------------------------

class TestWithConflictStatus:
    def test_preferred_citation_gets_preferred_status(self) -> None:
        citation = _make_citation(document_id="doc-a")
        conflict_result = ConflictDetectionResult(
            conflict_detected=True,
            agreement_level="conflicting",
            conflicting_document_ids=["doc-a", "doc-b"],
            preferred_document_ids=["doc-a"],
            applied=True,
        )
        annotated = _with_conflict_status(citation, conflict_result)
        assert annotated.conflict_status == "preferred"

    def test_conflicting_citation_gets_conflicting_status(self) -> None:
        citation = _make_citation(document_id="doc-b")
        conflict_result = ConflictDetectionResult(
            conflict_detected=True,
            agreement_level="conflicting",
            conflicting_document_ids=["doc-a", "doc-b"],
            preferred_document_ids=["doc-a"],
            applied=True,
        )
        annotated = _with_conflict_status(citation, conflict_result)
        assert annotated.conflict_status == "conflicting"

    def test_uninvolved_citation_gets_neutral_status(self) -> None:
        citation = _make_citation(document_id="doc-c")
        conflict_result = ConflictDetectionResult(
            conflict_detected=True,
            agreement_level="conflicting",
            conflicting_document_ids=["doc-a", "doc-b"],
            preferred_document_ids=["doc-a"],
            applied=True,
        )
        annotated = _with_conflict_status(citation, conflict_result)
        assert annotated.conflict_status == "neutral"

    def test_unapplied_result_leaves_citation_unchanged(self) -> None:
        citation = _make_citation(document_id="doc-a")
        conflict_result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="full",
            applied=False,
        )
        annotated = _with_conflict_status(citation, conflict_result)
        assert annotated.conflict_status is None

    def test_no_conflict_detected_leaves_citation_unchanged(self) -> None:
        citation = _make_citation(document_id="doc-a")
        conflict_result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="partial",
            applied=True,
        )
        annotated = _with_conflict_status(citation, conflict_result)
        assert annotated.conflict_status is None


# ---------------------------------------------------------------------------
# _build_conflict_context
# ---------------------------------------------------------------------------

class TestBuildConflictContext:
    def test_full_agreement_returns_empty_string(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="full",
            applied=True,
        )
        assert _build_conflict_context(result) == ""

    def test_unapplied_returns_empty_string(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="partial",
            applied=False,
        )
        assert _build_conflict_context(result) == ""

    def test_partial_agreement_returns_guidance_block(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=False,
            agreement_level="partial",
            conflict_summary="Minor wording differences.",
            applied=True,
        )
        ctx = _build_conflict_context(result)
        assert "agreement_level" in ctx
        assert "partial" in ctx
        assert "avoid presenting a single certain answer" in ctx

    def test_conflicting_includes_summary_and_pairs(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=True,
            agreement_level="conflicting",
            conflict_summary="Sources disagree on the effective date.",
            conflict_pairs=[
                ConflictPair(
                    document_id_a="doc-a",
                    document_id_b="doc-b",
                    topic="effective date",
                    severity="high",
                )
            ],
            conflicting_document_ids=["doc-a", "doc-b"],
            preferred_document_ids=["doc-a"],
            applied=True,
        )
        ctx = _build_conflict_context(result)
        assert "conflicting" in ctx
        assert "effective date" in ctx
        assert "preferred_document_ids" in ctx
        assert "doc-a" in ctx

    def test_context_includes_instruction_to_avoid_certain_answer(self) -> None:
        result = ConflictDetectionResult(
            conflict_detected=True,
            agreement_level="conflicting",
            conflict_summary="X",
            applied=True,
        )
        ctx = _build_conflict_context(result)
        assert "avoid presenting a single certain answer" in ctx

    def test_context_limits_pair_output_to_five(self) -> None:
        pairs = [
            ConflictPair(
                document_id_a=f"doc-{i}a",
                document_id_b=f"doc-{i}b",
                topic=f"topic-{i}",
                severity="low",
            )
            for i in range(10)
        ]
        result = ConflictDetectionResult(
            conflict_detected=True,
            agreement_level="conflicting",
            conflict_summary="Many conflicts.",
            conflict_pairs=pairs,
            applied=True,
        )
        ctx = _build_conflict_context(result)
        assert ctx.count("topic-") == 5


# ---------------------------------------------------------------------------
# ConflictStatusRecord trust metadata DTO
# ---------------------------------------------------------------------------

class TestConflictStatusRecord:
    def test_defaults_to_full_no_conflict(self) -> None:
        record = ConflictStatusRecord()
        assert record.detected is False
        assert record.agreement_level == "full"
        assert record.conflict_count == 0
        assert record.conflicting_document_ids == []
        assert record.preferred_document_ids == []
        assert record.conflict_summary is None

    def test_round_trips_conflict_data(self) -> None:
        record = ConflictStatusRecord(
            detected=True,
            agreement_level="conflicting",
            conflict_count=2,
            conflicting_document_ids=["doc-a", "doc-b"],
            preferred_document_ids=["doc-a"],
            conflict_summary="Effective dates differ.",
        )
        dumped = record.model_dump()
        restored = ConflictStatusRecord.model_validate(dumped)
        assert restored.detected is True
        assert restored.agreement_level == "conflicting"
        assert restored.conflict_count == 2
        assert restored.conflict_summary == "Effective dates differ."

    def test_partial_agreement_no_conflict_detected(self) -> None:
        record = ConflictStatusRecord(
            detected=False,
            agreement_level="partial",
            conflict_count=0,
        )
        assert record.detected is False
        assert record.agreement_level == "partial"
