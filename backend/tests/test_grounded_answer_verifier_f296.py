"""Tests for GroundedAnswerVerifier (F296).

Covers:
- LLM output schema validation (_VerifierOutput).
- Happy paths: supported / partially_supported / unsupported verdicts.
- Claim removal: final_answer reflects only supported sentences.
- Strict mode: unsupported verdict blanks the final_answer.
- Fallback: any LLM / parse failure returns original answer unchanged.
- Security: raw chunk text is never returned in the result.
- Safety: verifier skipped when answer is empty or chunks are empty.
- reason_codes allowlist enforcement (unknown codes are stripped).
- removed_claims length limits (200 chars, max 10 items).
- Evaluation: faithfulness and refusal accuracy.
- Latency tracking: latency_ms set on success, zero on fallback.
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

from app.domains.chat.services.grounded_answer_verifier import (
    GroundedAnswerVerifier,
    GroundedVerifierResult,
    VerifierChunk,
    _VerifierOutput,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    content: str
    model: str = "gpt-5.4-mini"
    prompt_tokens: int = 60
    completion_tokens: int = 40
    total_tokens: int = 100


def _make_service() -> GroundedAnswerVerifier:
    return GroundedAnswerVerifier(timeout_seconds=5.0)


def _mock_provider(response_json: str) -> AsyncMock:
    provider = AsyncMock()
    provider.complete.return_value = _FakeResponse(content=response_json)
    return provider


def _make_chunks(n: int = 2) -> list[VerifierChunk]:
    return [
        VerifierChunk(
            chunk_id=f"chunk-{i}",
            text=f"Source document text {i}. Policy states refund within 30 days.",
            similarity_score=0.9 - i * 0.05,
        )
        for i in range(n)
    ]


_SUPPORTED_JSON = """{
    "verdict": "supported",
    "revised_answer": "Refunds are processed within 30 days.",
    "removed_claims": [],
    "reason_codes": [],
    "claim_count": 1,
    "supported_claim_count": 1,
    "unsupported_claim_count": 0
}"""

_PARTIALLY_SUPPORTED_JSON = """{
    "verdict": "partially_supported",
    "revised_answer": "Refunds are processed within 30 days.",
    "removed_claims": ["claim about 14-day processing window (no source found)"],
    "reason_codes": ["no_source"],
    "claim_count": 2,
    "supported_claim_count": 1,
    "unsupported_claim_count": 1
}"""

_UNSUPPORTED_JSON = """{
    "verdict": "unsupported",
    "revised_answer": "",
    "removed_claims": ["all claims lack source support"],
    "reason_codes": ["no_source", "hallucinated_detail"],
    "claim_count": 2,
    "supported_claim_count": 0,
    "unsupported_claim_count": 2
}"""


# ---------------------------------------------------------------------------
# Unit: _VerifierOutput schema
# ---------------------------------------------------------------------------


class TestVerifierOutputSchema:
    def test_supported_verdict_parses(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "supported",
                "revised_answer": "The policy allows 30-day refunds.",
                "removed_claims": [],
                "reason_codes": [],
                "claim_count": 1,
                "supported_claim_count": 1,
                "unsupported_claim_count": 0,
            }
        )
        assert out.verdict == "supported"
        assert out.removed_claims == []
        assert out.reason_codes == []

    def test_partially_supported_parses(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial answer.",
                "removed_claims": ["unsupported claim description"],
                "reason_codes": ["no_source"],
                "claim_count": 2,
                "supported_claim_count": 1,
                "unsupported_claim_count": 1,
            }
        )
        assert out.verdict == "partially_supported"
        assert len(out.removed_claims) == 1
        assert out.reason_codes == ["no_source"]

    def test_unsupported_verdict_parses(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "unsupported",
                "revised_answer": "",
                "removed_claims": ["all claims unsupported"],
                "reason_codes": ["hallucinated_detail"],
                "claim_count": 3,
                "supported_claim_count": 0,
                "unsupported_claim_count": 3,
            }
        )
        assert out.verdict == "unsupported"
        assert out.supported_claim_count == 0

    def test_unknown_reason_codes_are_stripped(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "supported",
                "revised_answer": "Answer.",
                "removed_claims": [],
                "reason_codes": ["no_source", "UNKNOWN_CODE", "another_invalid"],
                "claim_count": 1,
                "supported_claim_count": 1,
                "unsupported_claim_count": 0,
            }
        )
        assert "UNKNOWN_CODE" not in out.reason_codes
        assert "another_invalid" not in out.reason_codes
        assert "no_source" in out.reason_codes

    def test_removed_claims_truncated_to_200_chars(self) -> None:
        long_claim = "x" * 300
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Short answer.",
                "removed_claims": [long_claim],
                "reason_codes": [],
                "claim_count": 2,
                "supported_claim_count": 1,
                "unsupported_claim_count": 1,
            }
        )
        assert len(out.removed_claims[0]) == 200

    def test_removed_claims_capped_at_10_items(self) -> None:
        many_claims = [f"claim {i}" for i in range(20)]
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial.",
                "removed_claims": many_claims,
                "reason_codes": [],
                "claim_count": 20,
                "supported_claim_count": 10,
                "unsupported_claim_count": 10,
            }
        )
        assert len(out.removed_claims) == 10

    def test_none_removed_claims_becomes_empty_list(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "supported",
                "revised_answer": "Answer.",
                "removed_claims": None,
                "reason_codes": None,
                "claim_count": 1,
                "supported_claim_count": 1,
                "unsupported_claim_count": 0,
            }
        )
        assert out.removed_claims == []
        assert out.reason_codes == []

    def test_all_allowed_reason_codes_accepted(self) -> None:
        allowed = [
            "no_source",
            "contradicts_context",
            "out_of_scope",
            "low_coverage",
            "hallucinated_detail",
            "ambiguous",
        ]
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial.",
                "removed_claims": [],
                "reason_codes": allowed,
                "claim_count": 6,
                "supported_claim_count": 3,
                "unsupported_claim_count": 3,
            }
        )
        assert set(out.reason_codes) == set(allowed)


# ---------------------------------------------------------------------------
# Unit: verify — happy paths
# ---------------------------------------------------------------------------


class TestVerifyHappyPaths:
    @pytest.mark.asyncio
    async def test_supported_verdict_returns_original_answer(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_SUPPORTED_JSON)
        answer = "Refunds are processed within 30 days."
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer=answer, chunks=_make_chunks())

        assert result.applied is True
        assert result.verdict == "supported"
        assert result.final_answer == "Refunds are processed within 30 days."
        assert result.verification_score == 1.0
        assert result.claim_count == 1
        assert result.supported_claim_count == 1
        assert result.unsupported_claim_count == 0
        assert result.removed_claims == []

    @pytest.mark.asyncio
    async def test_partially_supported_verdict_uses_revised_answer(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_PARTIALLY_SUPPORTED_JSON)
        answer = "Refunds are processed within 30 days. Processing takes 14 days."
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer=answer, chunks=_make_chunks())

        assert result.applied is True
        assert result.verdict == "partially_supported"
        assert result.final_answer == "Refunds are processed within 30 days."
        assert result.unsupported_claim_count == 1
        assert "no_source" in result.reason_codes
        assert len(result.removed_claims) == 1

    @pytest.mark.asyncio
    async def test_unsupported_verdict_standard_mode_preserves_fallback_answer(self) -> None:
        """Standard mode: unsupported verdict still returns a final_answer (revised or original)."""
        svc = _make_service()
        provider = _mock_provider(_UNSUPPORTED_JSON)
        answer = "The policy requires a 6-month waiting period."
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer=answer, chunks=_make_chunks(), mode="standard")

        assert result.verdict == "unsupported"
        # revised_answer is "", so we fall back to the original answer
        assert result.final_answer == answer

    @pytest.mark.asyncio
    async def test_unsupported_verdict_strict_mode_blanks_answer(self) -> None:
        """Strict mode: a fully unsupported answer is blanked so caller can return not_found."""
        svc = _make_service()
        provider = _mock_provider(_UNSUPPORTED_JSON)
        answer = "The policy requires a 6-month waiting period."
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer=answer, chunks=_make_chunks(), mode="strict")

        assert result.verdict == "unsupported"
        assert result.final_answer == ""

    @pytest.mark.asyncio
    async def test_partially_supported_strict_mode_keeps_revised_answer(self) -> None:
        """In strict mode, partially_supported still returns the revised answer (not blanked)."""
        svc = _make_service()
        provider = _mock_provider(_PARTIALLY_SUPPORTED_JSON)
        answer = "Refunds are processed within 30 days. Processing takes 14 days."
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer=answer, chunks=_make_chunks(), mode="strict")

        assert result.verdict == "partially_supported"
        assert result.final_answer == "Refunds are processed within 30 days."

    @pytest.mark.asyncio
    async def test_verification_score_computed_from_claim_counts(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_PARTIALLY_SUPPORTED_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="Any answer", chunks=_make_chunks()
            )

        # 1 supported / 2 total claims = 0.5
        assert result.verification_score == 0.5

    @pytest.mark.asyncio
    async def test_json_with_markdown_fences_still_parsed(self) -> None:
        """LLM may wrap JSON in markdown — parser extracts the JSON object."""
        svc = _make_service()
        wrapped = f"```json\n{_SUPPORTED_JSON}\n```"
        provider = _mock_provider(wrapped)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.verdict == "supported"

    @pytest.mark.asyncio
    async def test_latency_ms_set_on_success(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_SUPPORTED_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_model_and_provider_populated_on_success(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_SUPPORTED_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.model_name != ""
        assert result.provider_key != ""


# ---------------------------------------------------------------------------
# Unit: verify — fallback behaviour
# ---------------------------------------------------------------------------


class TestVerifyFallback:
    @pytest.mark.asyncio
    async def test_provider_exception_falls_back_to_original(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        provider.complete.side_effect = RuntimeError("network error")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks())

        assert result.applied is False
        assert result.verdict == "supported"
        assert result.final_answer == "Some answer."
        assert result.latency_ms == 0

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_original(self) -> None:
        svc = _make_service()
        provider = _mock_provider("not valid json at all")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks())

        assert result.applied is False
        assert result.final_answer == "Some answer."

    @pytest.mark.asyncio
    async def test_invalid_verdict_falls_back_to_original(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "definitely_yes", "revised_answer": "x", "removed_claims": [], '
            '"reason_codes": [], "claim_count": 1, "supported_claim_count": 1, "unsupported_claim_count": 0}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Original answer.", chunks=_make_chunks())

        assert result.applied is False
        assert result.final_answer == "Original answer."

    @pytest.mark.asyncio
    async def test_empty_answer_skips_provider_call(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="   ", chunks=_make_chunks())

        provider.complete.assert_not_called()
        assert result.applied is False
        assert result.verification_score == 1.0

    @pytest.mark.asyncio
    async def test_empty_chunks_skips_provider_call(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=[])

        provider.complete.assert_not_called()
        assert result.applied is False
        assert result.final_answer == "Some answer."

    @pytest.mark.asyncio
    async def test_empty_response_content_falls_back(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        provider.complete.return_value = _FakeResponse(content="")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks())

        assert result.applied is False
        assert result.final_answer == "Some answer."


# ---------------------------------------------------------------------------
# Security: no source text in result
# ---------------------------------------------------------------------------


class TestSecurityNoSourceTextLeak:
    @pytest.mark.asyncio
    async def test_removed_claims_do_not_contain_raw_chunk_text(self) -> None:
        """removed_claims must summarise what was removed from the answer,
        not quote raw source document text."""
        svc = _make_service()
        secret_text = "CONFIDENTIAL_INTERNAL_POLICY_TEXT_12345"
        chunks = [
            VerifierChunk(chunk_id="c1", text=f"Source: {secret_text}", similarity_score=0.9)
        ]
        # LLM properly returns only a claim summary, not raw source text
        provider = _mock_provider(
            '{"verdict": "partially_supported", "revised_answer": "Short answer.", '
            '"removed_claims": ["claim about processing time (no source)"], '
            '"reason_codes": ["no_source"], "claim_count": 2, '
            '"supported_claim_count": 1, "unsupported_claim_count": 1}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Original answer text.", chunks=chunks)

        for claim in result.removed_claims:
            assert secret_text not in claim, (
                "Raw source chunk text must not appear in removed_claims"
            )

    @pytest.mark.asyncio
    async def test_verifier_result_does_not_expose_chunk_text(self) -> None:
        """The GroundedVerifierResult dataclass must not contain chunk.text fields."""
        svc = _make_service()
        secret = "TOP_SECRET_DOCUMENT_CONTENT"
        chunks = [VerifierChunk(chunk_id="c1", text=secret, similarity_score=0.8)]
        provider = _mock_provider(_SUPPORTED_JSON)

        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Supported answer.", chunks=chunks)

        # Inspect result fields — none should contain the chunk's raw text
        import dataclasses
        result_values = [
            str(getattr(result, f.name)) for f in dataclasses.fields(result)
        ]
        for value in result_values:
            assert secret not in value, (
                f"Raw chunk text found in verifier result field: {value!r}"
            )


# ---------------------------------------------------------------------------
# Evaluation: faithfulness and refusal accuracy
# ---------------------------------------------------------------------------


class TestFaithfulnessEvaluation:
    @pytest.mark.asyncio
    async def test_fully_supported_answer_passes_verification(self) -> None:
        """An answer where every claim maps to a source should return verdict=supported."""
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "supported", "revised_answer": "Employees get 25 days of annual leave.", '
            '"removed_claims": [], "reason_codes": [], '
            '"claim_count": 1, "supported_claim_count": 1, "unsupported_claim_count": 0}'
        )
        chunks = [
            VerifierChunk(
                chunk_id="c1",
                text="Employees are entitled to 25 days of annual leave per year.",
                similarity_score=0.95,
            )
        ]
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="Employees get 25 days of annual leave.", chunks=chunks
            )

        assert result.verdict == "supported"
        assert result.verification_score == 1.0
        assert not result.removed_claims

    @pytest.mark.asyncio
    async def test_hallucinated_answer_triggers_unsupported_verdict(self) -> None:
        """An answer with no source grounding should return verdict=unsupported."""
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "unsupported", "revised_answer": "", '
            '"removed_claims": ["claim about 6-month waiting period (no source)"], '
            '"reason_codes": ["hallucinated_detail"], '
            '"claim_count": 1, "supported_claim_count": 0, "unsupported_claim_count": 1}'
        )
        chunks = [
            VerifierChunk(
                chunk_id="c1",
                text="Refunds must be requested within 30 days.",
                similarity_score=0.7,
            )
        ]
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="You must wait 6 months before requesting a refund.",
                chunks=chunks,
                mode="strict",
            )

        assert result.verdict == "unsupported"
        assert result.final_answer == ""  # strict mode blanked the answer
        assert "hallucinated_detail" in result.reason_codes

    @pytest.mark.asyncio
    async def test_mixed_answer_partially_supported(self) -> None:
        """An answer with one grounded and one hallucinated claim → partially_supported."""
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "partially_supported", '
            '"revised_answer": "The refund window is 30 days.", '
            '"removed_claims": ["claim about free return shipping (no source)"], '
            '"reason_codes": ["no_source"], '
            '"claim_count": 2, "supported_claim_count": 1, "unsupported_claim_count": 1}'
        )
        chunks = [
            VerifierChunk(
                chunk_id="c1",
                text="The refund window is 30 days from purchase date.",
                similarity_score=0.92,
            )
        ]
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="The refund window is 30 days. Return shipping is free.",
                chunks=chunks,
            )

        assert result.verdict == "partially_supported"
        assert "30 days" in result.final_answer
        assert result.unsupported_claim_count == 1
        assert result.verification_score == 0.5

    @pytest.mark.asyncio
    async def test_refusal_accuracy_unsupported_does_not_leak_answer(self) -> None:
        """In strict mode an unsupported verdict must blank the answer completely."""
        svc = _make_service()
        provider = _mock_provider(_UNSUPPORTED_JSON)
        original = "The CEO earns $10M annually according to our policy."
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer=original, chunks=_make_chunks(), mode="strict"
            )

        assert result.final_answer == ""
        assert original not in result.final_answer


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_single_chunk_verification(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_SUPPORTED_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="Supported answer.", chunks=_make_chunks(1)
            )

        assert result.applied is True
        assert result.verdict == "supported"

    @pytest.mark.asyncio
    async def test_many_chunks_all_used(self) -> None:
        """Verify that many chunks don't cause errors (prompt truncation happens inside)."""
        svc = _make_service()
        provider = _mock_provider(_SUPPORTED_JSON)
        many_chunks = _make_chunks(20)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=many_chunks)

        assert result.applied is True

    @pytest.mark.asyncio
    async def test_result_is_frozen_dataclass(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_SUPPORTED_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        with pytest.raises((AttributeError, TypeError)):
            result.verdict = "changed"  # type: ignore[misc]

    def test_fallback_static_method_always_safe(self) -> None:
        result = GroundedAnswerVerifier._fallback("test answer")
        assert isinstance(result, GroundedVerifierResult)
        assert result.final_answer == "test answer"
        assert result.applied is False
        assert result.verdict == "supported"
        assert result.verification_score == 1.0
        assert result.removed_claims == []
        assert result.latency_ms == 0

    @pytest.mark.asyncio
    async def test_whitespace_only_answer_skips_provider(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="   \n\t  ", chunks=_make_chunks())

        provider.complete.assert_not_called()
        assert result.applied is False

    @pytest.mark.asyncio
    async def test_zero_claim_count_does_not_divide_by_zero(self) -> None:
        """claim_count=0 in LLM output must not raise ZeroDivisionError."""
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "supported", "revised_answer": "Answer.", '
            '"removed_claims": [], "reason_codes": [], '
            '"claim_count": 0, "supported_claim_count": 0, "unsupported_claim_count": 0}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.verification_score == 0.0  # 0/max(1,0) = 0/1
        assert result.applied is True

    @pytest.mark.asyncio
    async def test_revised_answer_empty_falls_back_to_original_in_standard_mode(self) -> None:
        """If LLM returns empty revised_answer in standard mode, use the original answer."""
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "partially_supported", "revised_answer": "", '
            '"removed_claims": ["something"], "reason_codes": ["low_coverage"], '
            '"claim_count": 1, "supported_claim_count": 0, "unsupported_claim_count": 1}'
        )
        original = "Original answer that should be preserved."
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer=original, chunks=_make_chunks(), mode="standard")

        # empty revised_answer → fall back to original in standard mode
        assert result.final_answer == original

    @pytest.mark.asyncio
    async def test_latency_zero_on_fallback_from_exception(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        provider.complete.side_effect = TimeoutError("timeout")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.latency_ms == 0


# ---------------------------------------------------------------------------
# Integration-style: multi-claim answers
# ---------------------------------------------------------------------------


class TestMultiClaimAnswers:
    @pytest.mark.asyncio
    async def test_answer_with_all_claims_supported(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "supported", '
            '"revised_answer": "The notice period is 30 days. Refunds take 7 business days. '
            'Contact HR for exceptions.", '
            '"removed_claims": [], "reason_codes": [], '
            '"claim_count": 3, "supported_claim_count": 3, "unsupported_claim_count": 0}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer=(
                    "The notice period is 30 days. Refunds take 7 business days. "
                    "Contact HR for exceptions."
                ),
                chunks=_make_chunks(3),
            )

        assert result.verdict == "supported"
        assert result.claim_count == 3
        assert result.verification_score == 1.0

    @pytest.mark.asyncio
    async def test_answer_with_majority_unsupported_strict_mode(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "unsupported", "revised_answer": "", '
            '"removed_claims": ["3 unsupported claims about bonuses and leave"], '
            '"reason_codes": ["no_source", "hallucinated_detail"], '
            '"claim_count": 3, "supported_claim_count": 0, "unsupported_claim_count": 3}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="Bonus is 20%. Leave is 40 days. Stock options vest in 3 years.",
                chunks=[
                    VerifierChunk(
                        chunk_id="c1",
                        text="See the HR handbook for compensation details.",
                        similarity_score=0.5,
                    )
                ],
                mode="strict",
            )

        assert result.verdict == "unsupported"
        assert result.final_answer == ""
        assert result.verification_score == 0.0

    @pytest.mark.asyncio
    async def test_reason_codes_properly_propagated(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "partially_supported", "revised_answer": "Partial.", '
            '"removed_claims": ["one claim"], '
            '"reason_codes": ["contradicts_context", "ambiguous"], '
            '"claim_count": 2, "supported_claim_count": 1, "unsupported_claim_count": 1}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Two claims here.", chunks=_make_chunks())

        assert "contradicts_context" in result.reason_codes
        assert "ambiguous" in result.reason_codes
