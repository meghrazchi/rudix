"""Tests for QueryRewritingService (F295).

Covers:
- Scope preservation: rewriting never alters document_ids / org tenancy (they are downstream).
- Strategy routing: original / rewrite / decompose.
- Sub-query limits and normalisation.
- Fallback to original query on LLM or parse failure.
- Profile knobs: disable rewriting / decomposition via RagProfileConfig.
- Acronym expansion (rewrite strategy).
- Multi-part decomposition (decompose strategy).
- Regression: rewrite cannot widen access filters (unit-level check that the query string
  returned cannot reference documents outside what was requested).
"""

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

from app.domains.chat.services.query_rewriting_service import (
    QueryRewritingResult,
    QueryRewritingService,
    _RewritingOutput,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    content: str
    model: str = "gpt-5.4-mini"
    prompt_tokens: int = 50
    completion_tokens: int = 30
    total_tokens: int = 80


def _make_service(*, max_sub_queries: int = 4) -> QueryRewritingService:
    return QueryRewritingService(timeout_seconds=5.0, max_sub_queries=max_sub_queries)


def _mock_provider(response_json: str) -> AsyncMock:
    provider = AsyncMock()
    provider.complete.return_value = _FakeResponse(content=response_json)
    return provider


# ---------------------------------------------------------------------------
# Unit: _RewritingOutput schema
# ---------------------------------------------------------------------------


class TestRewritingOutputSchema:
    def test_original_strategy_parses(self) -> None:
        out = _RewritingOutput.model_validate(
            {
                "strategy": "original",
                "primary_query": "What is the refund policy?",
                "sub_queries": [],
            }
        )
        assert out.strategy == "original"
        assert out.sub_queries == []

    def test_rewrite_strategy_parses(self) -> None:
        out = _RewritingOutput.model_validate(
            {
                "strategy": "rewrite",
                "primary_query": "What is the PII data retention policy?",
                "sub_queries": [],
            }
        )
        assert out.strategy == "rewrite"
        assert out.sub_queries == []

    def test_decompose_strategy_parses_sub_queries(self) -> None:
        out = _RewritingOutput.model_validate(
            {
                "strategy": "decompose",
                "primary_query": "Data retention and access control policies",
                "sub_queries": ["What is the data retention policy?", "Who can access PII?"],
            }
        )
        assert out.strategy == "decompose"
        assert len(out.sub_queries) == 2

    def test_blank_sub_queries_are_dropped(self) -> None:
        out = _RewritingOutput.model_validate(
            {
                "strategy": "decompose",
                "primary_query": "Some query",
                "sub_queries": ["valid", "  ", "", "also valid"],
            }
        )
        assert out.sub_queries == ["valid", "also valid"]

    def test_none_sub_queries_returns_empty_list(self) -> None:
        out = _RewritingOutput.model_validate(
            {"strategy": "original", "primary_query": "Q?", "sub_queries": None}
        )
        assert out.sub_queries == []

    def test_long_sub_query_truncated_to_max(self) -> None:
        long = "x" * 2000
        out = _RewritingOutput.model_validate(
            {"strategy": "decompose", "primary_query": "Q", "sub_queries": [long]}
        )
        assert len(out.sub_queries[0]) == 1000


# ---------------------------------------------------------------------------
# Unit: service._apply_limits
# ---------------------------------------------------------------------------


class TestApplyLimits:
    def test_sub_queries_capped_at_max(self) -> None:
        parsed = _RewritingOutput(
            strategy="decompose",
            primary_query="Combined query",
            sub_queries=["Q1", "Q2", "Q3", "Q4"],
        )
        result = QueryRewritingService._apply_limits(parsed, max_sub_queries=2)
        assert len(result.sub_queries) == 2
        assert result.sub_queries == ["Q1", "Q2"]

    def test_decompose_with_no_sub_queries_falls_back_to_rewrite(self) -> None:
        parsed = _RewritingOutput(strategy="decompose", primary_query="Query", sub_queries=[])
        result = QueryRewritingService._apply_limits(parsed, max_sub_queries=4)
        assert result.strategy == "rewrite"
        assert result.sub_queries == []

    def test_non_decompose_strategy_clears_sub_queries(self) -> None:
        parsed = _RewritingOutput(
            strategy="rewrite",
            primary_query="Expanded query",
            sub_queries=["leaked sub-query"],
        )
        result = QueryRewritingService._apply_limits(parsed, max_sub_queries=4)
        assert result.sub_queries == []

    def test_original_strategy_passes_through(self) -> None:
        parsed = _RewritingOutput(strategy="original", primary_query="As is", sub_queries=[])
        result = QueryRewritingService._apply_limits(parsed, max_sub_queries=4)
        assert result.strategy == "original"
        assert result.primary_query == "As is"


# ---------------------------------------------------------------------------
# Unit: service.rewrite — happy paths
# ---------------------------------------------------------------------------


class TestRewriteHappyPaths:
    @pytest.mark.asyncio
    async def test_original_strategy_returns_original_query(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"strategy": "original", "primary_query": "What is the refund policy?", "sub_queries": []}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("What is the refund policy?")

        assert result.strategy == "original"
        assert result.primary_query == "What is the refund policy?"
        assert result.rewriting_applied is False
        assert result.decomposition_applied is False
        assert result.sub_queries == []
        assert result.original_query == "What is the refund policy?"

    @pytest.mark.asyncio
    async def test_rewrite_strategy_uses_rewritten_primary_query(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"strategy": "rewrite", "primary_query": "PII personally identifiable information retention policy", "sub_queries": []}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("What does the PII policy say about retention?")

        assert result.strategy == "rewrite"
        assert "personally identifiable information" in result.primary_query
        assert result.rewriting_applied is True
        assert result.decomposition_applied is False
        assert result.original_query == "What does the PII policy say about retention?"

    @pytest.mark.asyncio
    async def test_decompose_strategy_returns_sub_queries(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            """{
                "strategy": "decompose",
                "primary_query": "Data retention and access control",
                "sub_queries": [
                    "What is the data retention period for customer records?",
                    "Who has access to PII data?"
                ]
            }"""
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite(
                "How long are customer records retained and who can access them?"
            )

        assert result.strategy == "decompose"
        assert result.decomposition_applied is True
        assert len(result.sub_queries) == 2
        assert "retention" in result.sub_queries[0].lower()

    @pytest.mark.asyncio
    async def test_decompose_sets_rewriting_applied_when_primary_differs(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            """{
                "strategy": "decompose",
                "primary_query": "DIFFERENT primary query",
                "sub_queries": ["Sub Q1", "Sub Q2"]
            }"""
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("original question")

        assert result.rewriting_applied is True
        assert result.decomposition_applied is True

    @pytest.mark.asyncio
    async def test_json_with_surrounding_text_is_still_parsed(self) -> None:
        """LLM may wrap JSON in markdown — fallback parser extracts the object."""
        svc = _make_service()
        provider = _mock_provider(
            'Here is your result:\n```json\n{"strategy": "original", "primary_query": "Q?", "sub_queries": []}\n```'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("Q?")

        assert result.strategy == "original"


# ---------------------------------------------------------------------------
# Unit: service.rewrite — fallback behaviour
# ---------------------------------------------------------------------------


class TestRewriteFallback:
    @pytest.mark.asyncio
    async def test_provider_exception_falls_back_to_original(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        provider.complete.side_effect = RuntimeError("network error")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("What is the refund policy?")

        assert result.strategy == "original"
        assert result.primary_query == "What is the refund policy?"
        assert result.rewriting_applied is False
        assert result.latency_ms == 0

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_original(self) -> None:
        svc = _make_service()
        provider = _mock_provider("not json at all")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("What is the refund policy?")

        assert result.original_query == "What is the refund policy?"
        assert result.primary_query == "What is the refund policy?"
        assert result.rewriting_applied is False

    @pytest.mark.asyncio
    async def test_invalid_strategy_falls_back_to_original(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"strategy": "hallucinated_strategy", "primary_query": "Q", "sub_queries": []}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("original?")

        assert result.primary_query == "original?"
        assert result.rewriting_applied is False

    @pytest.mark.asyncio
    async def test_empty_question_returns_fallback_without_calling_provider(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("   ")

        provider.complete.assert_not_called()
        assert result.primary_query == "   "
        assert result.rewriting_applied is False

    @pytest.mark.asyncio
    async def test_empty_response_content_falls_back(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        provider.complete.return_value = _FakeResponse(content="")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("Some question?")

        assert result.rewriting_applied is False
        assert result.primary_query == "Some question?"


# ---------------------------------------------------------------------------
# Unit: profile knobs
# ---------------------------------------------------------------------------


class TestProfileKnobs:
    @pytest.mark.asyncio
    async def test_rewriting_disabled_by_profile_returns_original(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"strategy": "rewrite", "primary_query": "Expanded query", "sub_queries": []}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite(
                "Short query",
                profile_rewriting_enabled=False,
            )

        assert result.strategy == "original"
        assert result.primary_query == "Short query"
        assert result.rewriting_applied is False

    @pytest.mark.asyncio
    async def test_decomposition_disabled_by_profile_caps_sub_queries_to_zero(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            """{
                "strategy": "decompose",
                "primary_query": "Combined",
                "sub_queries": ["Q1", "Q2"]
            }"""
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite(
                "Multi-part question",
                profile_decomposition_enabled=False,
            )

        assert result.decomposition_applied is False
        assert result.sub_queries == []

    @pytest.mark.asyncio
    async def test_custom_max_sub_queries_overrides_default(self) -> None:
        svc = _make_service(max_sub_queries=10)
        provider = _mock_provider(
            """{
                "strategy": "decompose",
                "primary_query": "Big question",
                "sub_queries": ["Q1", "Q2", "Q3"]
            }"""
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("Big question", max_sub_queries=2)

        # max_sub_queries=2 passed as override should win over service default=10
        assert len(result.sub_queries) == 2


# ---------------------------------------------------------------------------
# Scope preservation regression tests
# ---------------------------------------------------------------------------


class TestScopePreservation:
    """Verify that query rewriting cannot expand access beyond the provided scope.

    Source filters (document_ids, org_id) are applied downstream in the retrieval
    layer and are never touched by QueryRewritingService. This test suite confirms
    that the rewritten queries do not reference document IDs, collection names, or
    org tenancy identifiers that were not already in the original question.
    """

    @pytest.mark.asyncio
    async def test_rewritten_query_does_not_introduce_document_ids(self) -> None:
        svc = _make_service()
        safe_primary = "What is the data retention policy for customer contracts?"
        provider = _mock_provider(
            f'{{"strategy": "rewrite", "primary_query": "{safe_primary}", "sub_queries": []}}'
        )
        original = "retention policy"
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite(original)

        # The rewritten query must not contain any UUID-like pattern not in original.
        import re

        uuid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
        )
        assert not uuid_pattern.search(result.primary_query), (
            "Rewritten query must not introduce document UUIDs"
        )

    @pytest.mark.asyncio
    async def test_sub_queries_do_not_reference_org_ids(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            """{
                "strategy": "decompose",
                "primary_query": "Compliance and audit requirements",
                "sub_queries": [
                    "What are the compliance requirements?",
                    "What are the audit trail requirements?"
                ]
            }"""
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("What are our compliance and audit requirements?")

        import re

        uuid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
        )
        for sub_q in result.sub_queries:
            assert not uuid_pattern.search(sub_q), (
                f"Sub-query introduced unexpected UUID: {sub_q!r}"
            )

    @pytest.mark.asyncio
    async def test_original_query_always_preserved(self) -> None:
        """original_query must always equal the user's verbatim input."""
        svc = _make_service()
        original = "What does GDPR say about data subject rights?"
        provider = _mock_provider(
            """{
                "strategy": "rewrite",
                "primary_query": "GDPR General Data Protection Regulation data subject rights access erasure rectification",
                "sub_queries": []
            }"""
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite(original)

        assert result.original_query == original, (
            "original_query must be the verbatim user input, not the rewritten query"
        )

    @pytest.mark.asyncio
    async def test_scope_not_altered_on_decomposition(self) -> None:
        """Each sub-query must remain within the semantic scope of the original question."""
        svc = _make_service()
        original = "What are the SLA commitments for tier-1 and tier-2 support?"
        provider = _mock_provider(
            """{
                "strategy": "decompose",
                "primary_query": "SLA commitments support tier levels",
                "sub_queries": [
                    "What are the SLA commitments for tier-1 support?",
                    "What are the SLA commitments for tier-2 support?"
                ]
            }"""
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite(original)

        assert result.original_query == original
        assert len(result.sub_queries) == 2
        for sub_q in result.sub_queries:
            assert "SLA" in sub_q or "tier" in sub_q.lower()


# ---------------------------------------------------------------------------
# Integration-style tests: multi-part questions
# ---------------------------------------------------------------------------


class TestMultiPartQuestions:
    @pytest.mark.asyncio
    async def test_three_part_question_decomposed_and_capped(self) -> None:
        svc = _make_service(max_sub_queries=2)
        provider = _mock_provider(
            """{
                "strategy": "decompose",
                "primary_query": "Vendor onboarding payment process and escalation contacts",
                "sub_queries": [
                    "How do I onboard a new vendor?",
                    "What is the payment approval process?",
                    "Who are the escalation contacts for vendor issues?"
                ]
            }"""
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite(
                "How do I onboard a new vendor, what is the payment process, and who do I escalate to?"
            )

        assert result.decomposition_applied is True
        assert len(result.sub_queries) == 2

    @pytest.mark.asyncio
    async def test_simple_question_not_decomposed(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"strategy": "original", "primary_query": "What is the password policy?", "sub_queries": []}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("What is the password policy?")

        assert result.decomposition_applied is False
        assert result.sub_queries == []
        assert result.primary_query == "What is the password policy?"

    @pytest.mark.asyncio
    async def test_acronym_heavy_question_rewritten(self) -> None:
        svc = _make_service()
        expanded = "HIPAA Health Insurance Portability and Accountability Act PHI protected health information breach notification requirements"
        provider = _mock_provider(
            f'{{"strategy": "rewrite", "primary_query": "{expanded}", "sub_queries": []}}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("What are the HIPAA PHI breach notification requirements?")

        assert result.rewriting_applied is True
        assert "HIPAA" in result.primary_query or "Health Insurance" in result.primary_query

    @pytest.mark.asyncio
    async def test_latency_is_tracked_on_success(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"strategy": "original", "primary_query": "Q?", "sub_queries": []}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("Q?")

        # latency_ms should be set (non-negative; may be 0 in fast mocked tests)
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_latency_is_zero_on_fallback(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        provider.complete.side_effect = RuntimeError("boom")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("Q?")

        assert result.latency_ms == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_whitespace_only_question_skips_provider(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("   \t\n  ")

        provider.complete.assert_not_called()
        assert result.rewriting_applied is False

    @pytest.mark.asyncio
    async def test_max_length_sub_query_safely_stored(self) -> None:
        long_sub = "word " * 250
        svc = _make_service()
        provider = _mock_provider(
            f'{{"strategy": "decompose", "primary_query": "Q", "sub_queries": ["{long_sub.strip()}"]}}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("Q")

        for sub_q in result.sub_queries:
            assert len(sub_q) <= 1000

    @pytest.mark.asyncio
    async def test_result_is_frozen_dataclass(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"strategy": "original", "primary_query": "Q?", "sub_queries": []}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.rewrite("Q?")

        with pytest.raises((AttributeError, TypeError)):
            result.strategy = "changed"  # type: ignore[misc]

    def test_fallback_static_method_always_safe(self) -> None:
        result = QueryRewritingService._fallback("test question")
        assert isinstance(result, QueryRewritingResult)
        assert result.primary_query == "test question"
        assert result.rewriting_applied is False
        assert result.decomposition_applied is False
        assert result.sub_queries == []
