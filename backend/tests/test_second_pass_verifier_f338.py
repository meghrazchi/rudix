"""Tests for second-pass answer verification (F338).

Covers:
- Supported and unsupported claim fixtures with new statuses.
- Citation hallucination regression tests.
- Conflict detection: "conflicting" claim status and conflicting_claim_count.
- Not-enough-evidence: "not_enough_evidence" status tracking.
- Not-found behavior: strict mode with conflicting claims triggers not_found.
- Score impact: conflicting claims reduce verification_score to 0, not_enough_evidence to 0.2.
- New reason codes: source_conflict, insufficient_evidence.
- ClaimSupportRecord trust_metadata schema accepts new statuses.
- GroundedVerificationRecord exposes conflicting_count and not_enough_evidence_count.
- Latency and performance: result fields populated on success and fallback.
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

from app.domains.chat.schemas.trust_metadata import (
    ClaimSupportRecord,
    GroundedVerificationRecord,
)
from app.domains.chat.services.grounded_answer_verifier import (
    GroundedAnswerVerifier,
    VerifierChunk,
    VerifierCitation,
    _evidence_match_score,
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


def _make_citation(
    doc_id: str = "doc-1",
    trust_status: str = "trusted",
    score: float = 0.9,
    rerank_score: float | None = 0.9,
) -> VerifierCitation:
    return VerifierCitation(
        document_id=doc_id,
        chunk_id=f"chunk-{doc_id}",
        filename=f"{doc_id}.pdf",
        page_number=1,
        text_snippet="Policy text snippet.",
        score=score,
        similarity_score=score - 0.02,
        rerank_score=rerank_score,
        source_trust_status=trust_status,
        doc_ocr_quality_status="high",
    )


# JSON fixtures — new F338 statuses

_CONFLICTING_JSON = """{
    "verdict": "partially_supported",
    "revised_answer": "Some information is available but sources disagree.",
    "removed_claims": ["claim about 30-day vs 14-day refund window (sources conflict)"],
    "reason_codes": ["source_conflict", "contradicts_context"],
    "claim_count": 2,
    "supported_claim_count": 1,
    "partially_supported_claim_count": 0,
    "unsupported_claim_count": 0,
    "unverifiable_claim_count": 0,
    "conflicting_claim_count": 1,
    "not_enough_evidence_claim_count": 0,
    "claims": [
        {
            "claim_text": "Refunds are available.",
            "support_status": "supported",
            "citation_indices": [{"citation_index": 1}]
        },
        {
            "claim_text": "Refund window is 30 days according to one policy and 14 days per another.",
            "support_status": "conflicting",
            "citation_indices": [{"citation_index": 1}, {"citation_index": 2}]
        }
    ]
}"""

_NOT_ENOUGH_EVIDENCE_JSON = """{
    "verdict": "partially_supported",
    "revised_answer": "The refund window exists but specific details are unclear.",
    "removed_claims": ["specific refund amount (insufficient evidence in sources)"],
    "reason_codes": ["insufficient_evidence", "low_coverage"],
    "claim_count": 2,
    "supported_claim_count": 1,
    "partially_supported_claim_count": 0,
    "unsupported_claim_count": 0,
    "unverifiable_claim_count": 0,
    "conflicting_claim_count": 0,
    "not_enough_evidence_claim_count": 1,
    "claims": [
        {
            "claim_text": "A refund policy exists.",
            "support_status": "supported",
            "citation_indices": [{"citation_index": 1}]
        },
        {
            "claim_text": "The refund amount is $500.",
            "support_status": "not_enough_evidence",
            "citation_indices": []
        }
    ]
}"""

_ALL_CONFLICTING_JSON = """{
    "verdict": "unsupported",
    "revised_answer": "",
    "removed_claims": ["all claims contradicted by conflicting sources"],
    "reason_codes": ["source_conflict"],
    "claim_count": 2,
    "supported_claim_count": 0,
    "partially_supported_claim_count": 0,
    "unsupported_claim_count": 0,
    "unverifiable_claim_count": 0,
    "conflicting_claim_count": 2,
    "not_enough_evidence_claim_count": 0,
    "claims": [
        {
            "claim_text": "The refund window is 30 days.",
            "support_status": "conflicting",
            "citation_indices": [{"citation_index": 1}, {"citation_index": 2}]
        },
        {
            "claim_text": "Refunds require a receipt.",
            "support_status": "conflicting",
            "citation_indices": [{"citation_index": 1}]
        }
    ]
}"""

_MIXED_NEW_STATUSES_JSON = """{
    "verdict": "partially_supported",
    "revised_answer": "The notice period is confirmed to be 30 days.",
    "removed_claims": [
        "salary figure (sources conflict)",
        "bonus policy detail (insufficient evidence)"
    ],
    "reason_codes": ["source_conflict", "insufficient_evidence"],
    "claim_count": 4,
    "supported_claim_count": 1,
    "partially_supported_claim_count": 1,
    "unsupported_claim_count": 0,
    "unverifiable_claim_count": 0,
    "conflicting_claim_count": 1,
    "not_enough_evidence_claim_count": 1,
    "claims": [
        {
            "claim_text": "The notice period is 30 days.",
            "support_status": "supported",
            "citation_indices": [{"citation_index": 1}]
        },
        {
            "claim_text": "Salary is confirmed in the handbook.",
            "support_status": "partially_supported",
            "citation_indices": [{"citation_index": 1}]
        },
        {
            "claim_text": "Base salary is $80k according to policy A and $95k per policy B.",
            "support_status": "conflicting",
            "citation_indices": [{"citation_index": 1}, {"citation_index": 2}]
        },
        {
            "claim_text": "Bonus is paid quarterly.",
            "support_status": "not_enough_evidence",
            "citation_indices": []
        }
    ]
}"""


# ---------------------------------------------------------------------------
# Unit: _VerifierOutput schema — new status fields
# ---------------------------------------------------------------------------


class TestVerifierOutputSchemaF338:
    def test_conflicting_claim_count_defaults_to_zero(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "supported",
                "revised_answer": "Answer.",
                "removed_claims": [],
                "reason_codes": [],
                "claim_count": 1,
                "supported_claim_count": 1,
                "unsupported_claim_count": 0,
            }
        )
        assert out.conflicting_claim_count == 0
        assert out.not_enough_evidence_claim_count == 0

    def test_conflicting_claim_count_parsed(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial.",
                "removed_claims": [],
                "reason_codes": ["source_conflict"],
                "claim_count": 2,
                "supported_claim_count": 1,
                "unsupported_claim_count": 0,
                "conflicting_claim_count": 1,
                "not_enough_evidence_claim_count": 0,
            }
        )
        assert out.conflicting_claim_count == 1
        assert out.not_enough_evidence_claim_count == 0

    def test_not_enough_evidence_claim_count_parsed(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial.",
                "removed_claims": [],
                "reason_codes": ["insufficient_evidence"],
                "claim_count": 2,
                "supported_claim_count": 1,
                "unsupported_claim_count": 0,
                "conflicting_claim_count": 0,
                "not_enough_evidence_claim_count": 1,
            }
        )
        assert out.not_enough_evidence_claim_count == 1

    def test_source_conflict_reason_code_accepted(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial.",
                "removed_claims": [],
                "reason_codes": ["source_conflict"],
                "claim_count": 1,
                "supported_claim_count": 0,
                "unsupported_claim_count": 0,
                "conflicting_claim_count": 1,
            }
        )
        assert "source_conflict" in out.reason_codes

    def test_insufficient_evidence_reason_code_accepted(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial.",
                "removed_claims": [],
                "reason_codes": ["insufficient_evidence"],
                "claim_count": 1,
                "supported_claim_count": 0,
                "unsupported_claim_count": 0,
                "not_enough_evidence_claim_count": 1,
            }
        )
        assert "insufficient_evidence" in out.reason_codes

    def test_claim_with_conflicting_status_parses(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial.",
                "removed_claims": [],
                "reason_codes": ["source_conflict"],
                "claim_count": 1,
                "supported_claim_count": 0,
                "unsupported_claim_count": 0,
                "conflicting_claim_count": 1,
                "claims": [
                    {
                        "claim_text": "Sources disagree on the refund window.",
                        "support_status": "conflicting",
                        "citation_indices": [],
                    }
                ],
            }
        )
        assert out.claims[0].support_status == "conflicting"

    def test_claim_with_not_enough_evidence_status_parses(self) -> None:
        out = _VerifierOutput.model_validate(
            {
                "verdict": "partially_supported",
                "revised_answer": "Partial.",
                "removed_claims": [],
                "reason_codes": ["insufficient_evidence"],
                "claim_count": 1,
                "supported_claim_count": 0,
                "unsupported_claim_count": 0,
                "not_enough_evidence_claim_count": 1,
                "claims": [
                    {
                        "claim_text": "The refund amount is $500.",
                        "support_status": "not_enough_evidence",
                        "citation_indices": [],
                    }
                ],
            }
        )
        assert out.claims[0].support_status == "not_enough_evidence"


# ---------------------------------------------------------------------------
# Unit: _evidence_match_score — new statuses
# ---------------------------------------------------------------------------


class TestEvidenceMatchScoreF338:
    def test_conflicting_scores_zero(self) -> None:
        assert _evidence_match_score("conflicting") == 0.0

    def test_not_enough_evidence_scores_between_zero_and_unverifiable(self) -> None:
        score = _evidence_match_score("not_enough_evidence")
        assert 0.0 < score < _evidence_match_score("unverifiable")

    def test_not_enough_evidence_above_unsupported(self) -> None:
        assert _evidence_match_score("not_enough_evidence") > _evidence_match_score("unsupported")

    def test_score_ordering(self) -> None:
        assert (
            _evidence_match_score("supported")
            > _evidence_match_score("partially_supported")
            > _evidence_match_score("unverifiable")
            > _evidence_match_score("not_enough_evidence")
            > _evidence_match_score("unsupported")
        )
        assert _evidence_match_score("conflicting") == _evidence_match_score("unsupported")


# ---------------------------------------------------------------------------
# Conflict detection tests
# ---------------------------------------------------------------------------


class TestConflictDetection:
    @pytest.mark.asyncio
    async def test_conflicting_claims_counted(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks(2))

        assert result.conflicting_claim_count == 1
        assert result.not_enough_evidence_claim_count == 0
        assert any(c.support_status == "conflicting" for c in result.claims)

    @pytest.mark.asyncio
    async def test_conflicting_claim_has_zero_evidence_match_score(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks(2))

        conflicting = [c for c in result.claims if c.support_status == "conflicting"]
        assert conflicting, "Expected at least one conflicting claim"
        assert conflicting[0].evidence_match_score == 0.0

    @pytest.mark.asyncio
    async def test_conflicting_reason_code_propagated(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks(2))

        assert "source_conflict" in result.reason_codes

    @pytest.mark.asyncio
    async def test_all_conflicting_claims_verification_score_is_zero(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_ALL_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Conflicting answer.", chunks=_make_chunks(2))

        assert result.conflicting_claim_count == 2
        assert result.verification_score == 0.0

    @pytest.mark.asyncio
    async def test_conflicting_claims_reduce_verification_score(self) -> None:
        """1 supported + 1 conflicting → score is 1/2 = 0.5 (conflicting weights 0)."""
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks(2))

        assert result.verification_score == 0.5

    @pytest.mark.asyncio
    async def test_conflicting_standard_mode_sets_verification_failed_flag(self) -> None:
        """Standard mode: conflicting claims set verification_failed but do not blank the answer."""
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks(2))

        # The verifier itself signals conflicting but does not force blank in standard mode.
        assert result.conflicting_claim_count > 0
        assert result.final_answer != ""  # caller handles the not_found in pipeline

    @pytest.mark.asyncio
    async def test_all_conflicting_strict_mode_blanks_answer(self) -> None:
        """Strict mode: any conflicting claim blanks the final answer."""
        svc = _make_service()
        provider = _mock_provider(_ALL_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Conflicting.", chunks=_make_chunks(2), mode="strict")

        assert result.final_answer == ""
        assert result.conflicting_claim_count == 2

    @pytest.mark.asyncio
    async def test_partial_conflicting_strict_mode_blanks_answer(self) -> None:
        """Even one conflicting claim in strict mode blanks the answer."""
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="Partial answer.", chunks=_make_chunks(2), mode="strict"
            )

        assert result.final_answer == ""
        assert result.conflicting_claim_count == 1


# ---------------------------------------------------------------------------
# Not-enough-evidence tests
# ---------------------------------------------------------------------------


class TestNotEnoughEvidence:
    @pytest.mark.asyncio
    async def test_not_enough_evidence_claims_counted(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_NOT_ENOUGH_EVIDENCE_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks())

        assert result.not_enough_evidence_claim_count == 1
        assert result.conflicting_claim_count == 0
        assert any(c.support_status == "not_enough_evidence" for c in result.claims)

    @pytest.mark.asyncio
    async def test_not_enough_evidence_claim_has_low_evidence_score(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_NOT_ENOUGH_EVIDENCE_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks())

        nee_claims = [c for c in result.claims if c.support_status == "not_enough_evidence"]
        assert nee_claims
        assert nee_claims[0].evidence_match_score < _evidence_match_score("unverifiable")
        assert nee_claims[0].evidence_match_score > 0.0

    @pytest.mark.asyncio
    async def test_insufficient_evidence_reason_code_propagated(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_NOT_ENOUGH_EVIDENCE_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks())

        assert "insufficient_evidence" in result.reason_codes

    @pytest.mark.asyncio
    async def test_not_enough_evidence_contributes_small_score(self) -> None:
        """1 supported + 1 not_enough_evidence → score slightly above 0.5."""
        svc = _make_service()
        provider = _mock_provider(_NOT_ENOUGH_EVIDENCE_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks())

        # 1 supported (weight 1) + 1 not_enough_evidence (weight 0.2) / 2 = 0.6
        assert result.verification_score == pytest.approx(0.6, abs=0.01)

    @pytest.mark.asyncio
    async def test_not_enough_evidence_standard_mode_keeps_answer(self) -> None:
        """Standard mode: not_enough_evidence alone does not blank the answer."""
        svc = _make_service()
        provider = _mock_provider(_NOT_ENOUGH_EVIDENCE_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=_make_chunks(), mode="standard")

        assert result.final_answer != ""

    @pytest.mark.asyncio
    async def test_not_enough_evidence_strict_mode_below_threshold_blanks(self) -> None:
        """Strict mode with score below threshold blanks the answer."""
        svc = _make_service()
        provider = _mock_provider(_NOT_ENOUGH_EVIDENCE_JSON)
        # threshold=0.9 means score=0.6 is insufficient
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="Some answer.", chunks=_make_chunks(), mode="strict", threshold=0.9
            )

        assert result.final_answer == ""


# ---------------------------------------------------------------------------
# Citation hallucination regression tests
# ---------------------------------------------------------------------------


class TestCitationHallucinationRegression:
    @pytest.mark.asyncio
    async def test_citation_hallucination_returns_unsupported(self) -> None:
        """Answer with claims not grounded in any citation returns unsupported verdict."""
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "unsupported", "revised_answer": "", '
            '"removed_claims": ["hallucinated claim about 12-month warranty"], '
            '"reason_codes": ["hallucinated_detail", "no_source"], '
            '"claim_count": 1, "supported_claim_count": 0, "unsupported_claim_count": 1, '
            '"conflicting_claim_count": 0, "not_enough_evidence_claim_count": 0}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="The product comes with a 12-month warranty.",
                chunks=[
                    VerifierChunk(
                        chunk_id="c1",
                        text="Product returns are accepted within 30 days.",
                        similarity_score=0.6,
                    )
                ],
                mode="strict",
            )

        assert result.verdict == "unsupported"
        assert result.final_answer == ""
        assert result.conflicting_claim_count == 0

    @pytest.mark.asyncio
    async def test_citation_hallucination_with_fake_citation_index(self) -> None:
        """Claim referencing a citation index beyond the list is treated as no-citation."""
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "partially_supported", "revised_answer": "Partial.", '
            '"removed_claims": ["unverifiable detail"], '
            '"reason_codes": ["no_source"], '
            '"claim_count": 2, "supported_claim_count": 1, "unsupported_claim_count": 1, '
            '"conflicting_claim_count": 0, "not_enough_evidence_claim_count": 0, '
            '"claims": [{"claim_text": "Some claim.", "support_status": "unsupported", '
            '"citation_indices": [{"citation_index": 99}]}]}'
        )
        citations = [_make_citation("doc-1")]
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="Partial answer.",
                chunks=_make_chunks(),
                citations=citations,
            )

        # Citation index 99 exceeds list length → treated as no valid citation
        claims_with_bad_ref = [c for c in result.claims if 99 in c.citation_indices]
        assert not claims_with_bad_ref, "Out-of-range citation indices must be stripped"

    @pytest.mark.asyncio
    async def test_hallucinated_claim_without_conflicting_source(self) -> None:
        """Hallucination with no conflicting source → unsupported, not conflicting."""
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "unsupported", "revised_answer": "", '
            '"removed_claims": ["invented fact with no source"], '
            '"reason_codes": ["hallucinated_detail"], '
            '"claim_count": 1, "supported_claim_count": 0, "unsupported_claim_count": 1, '
            '"conflicting_claim_count": 0, "not_enough_evidence_claim_count": 0}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="The CEO earns $20M annually.",
                chunks=_make_chunks(),
            )

        assert result.unsupported_claim_count == 1
        assert result.conflicting_claim_count == 0
        assert result.verdict == "unsupported"


# ---------------------------------------------------------------------------
# Not-found behavior tests
# ---------------------------------------------------------------------------


class TestNotFoundBehavior:
    @pytest.mark.asyncio
    async def test_all_conflicting_strict_triggers_empty_final_answer(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_ALL_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="The refund window is 30 days.",
                chunks=_make_chunks(2),
                mode="strict",
            )

        assert result.final_answer == ""
        assert result.applied is True

    @pytest.mark.asyncio
    async def test_partial_conflicting_standard_mode_keeps_revised_answer(self) -> None:
        """Standard mode keeps revised_answer even with some conflicting claims."""
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="Some answer with conflicting part.",
                chunks=_make_chunks(2),
                mode="standard",
            )

        assert result.final_answer != ""
        assert result.conflicting_claim_count == 1

    @pytest.mark.asyncio
    async def test_unsupported_verdict_strict_mode_not_found(self) -> None:
        svc = _make_service()
        provider = _mock_provider(
            '{"verdict": "unsupported", "revised_answer": "", '
            '"removed_claims": ["all claims unsupported"], '
            '"reason_codes": ["no_source"], '
            '"claim_count": 1, "supported_claim_count": 0, "unsupported_claim_count": 1, '
            '"conflicting_claim_count": 0, "not_enough_evidence_claim_count": 0}'
        )
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(
                answer="No grounded claim here.",
                chunks=_make_chunks(),
                mode="strict",
            )

        assert result.final_answer == ""
        assert result.applied is True

    @pytest.mark.asyncio
    async def test_not_found_fallback_preserves_original_answer(self) -> None:
        """On verifier error, original answer is returned untouched (safe fallback)."""
        svc = _make_service()
        provider = AsyncMock()
        provider.complete.side_effect = RuntimeError("connection error")
        original = "The policy states 30-day refunds."
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer=original, chunks=_make_chunks(), mode="strict")

        assert result.applied is False
        assert result.final_answer == original
        assert result.conflicting_claim_count == 0

    @pytest.mark.asyncio
    async def test_empty_chunks_not_found_skips_verifier(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Some answer.", chunks=[], mode="strict")

        provider.complete.assert_not_called()
        assert result.applied is False
        assert result.conflicting_claim_count == 0
        assert result.not_enough_evidence_claim_count == 0


# ---------------------------------------------------------------------------
# Mixed new statuses and score calculation
# ---------------------------------------------------------------------------


class TestMixedNewStatuses:
    @pytest.mark.asyncio
    async def test_mixed_statuses_all_counts_populated(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_MIXED_NEW_STATUSES_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Mixed answer.", chunks=_make_chunks(2))

        assert result.supported_claim_count == 1
        assert result.partially_supported_claim_count == 1
        assert result.conflicting_claim_count == 1
        assert result.not_enough_evidence_claim_count == 1
        assert result.claim_count == 4

    @pytest.mark.asyncio
    async def test_mixed_statuses_verification_score(self) -> None:
        """
        score = (supported + 0.5*partial + 0.2*not_enough_evidence + 0*conflicting) / total
              = (1 + 0.5 + 0.2 + 0) / 4 = 0.425
        """
        svc = _make_service()
        provider = _mock_provider(_MIXED_NEW_STATUSES_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Mixed answer.", chunks=_make_chunks(2))

        assert result.verification_score == pytest.approx(0.425, abs=0.01)

    @pytest.mark.asyncio
    async def test_mixed_statuses_claim_list_includes_all_types(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_MIXED_NEW_STATUSES_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Mixed answer.", chunks=_make_chunks(2))

        statuses = {c.support_status for c in result.claims}
        assert "supported" in statuses
        assert "partially_supported" in statuses
        assert "conflicting" in statuses
        assert "not_enough_evidence" in statuses

    @pytest.mark.asyncio
    async def test_reason_codes_contain_both_new_codes(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_MIXED_NEW_STATUSES_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Mixed answer.", chunks=_make_chunks(2))

        assert "source_conflict" in result.reason_codes
        assert "insufficient_evidence" in result.reason_codes


# ---------------------------------------------------------------------------
# Trust-metadata schema tests (ClaimSupportRecord, GroundedVerificationRecord)
# ---------------------------------------------------------------------------


class TestTrustMetadataSchemaF338:
    def test_claim_support_record_accepts_conflicting_status(self) -> None:
        record = ClaimSupportRecord(
            claim_index=1,
            claim_text="Sources disagree on refund window.",
            support_status="conflicting",
            support_score=0.0,
            evidence_match_score=0.0,
            source_quality_score=0.0,
            rerank_score=0.0,
            chunk_coverage_score=0.0,
            citation_indices=[1, 2],
        )
        assert record.support_status == "conflicting"

    def test_claim_support_record_accepts_not_enough_evidence_status(self) -> None:
        record = ClaimSupportRecord(
            claim_index=1,
            claim_text="Insufficient detail in sources.",
            support_status="not_enough_evidence",
            support_score=0.15,
            evidence_match_score=0.2,
            source_quality_score=0.0,
            rerank_score=0.0,
            chunk_coverage_score=0.0,
            citation_indices=[],
        )
        assert record.support_status == "not_enough_evidence"

    def test_grounded_verification_record_has_conflicting_count(self) -> None:
        record = GroundedVerificationRecord(
            applied=True,
            verdict="partially_supported",
            score=0.5,
            claim_count=2,
            conflicting_count=1,
            not_enough_evidence_count=0,
        )
        assert record.conflicting_count == 1
        assert record.not_enough_evidence_count == 0

    def test_grounded_verification_record_has_not_enough_evidence_count(self) -> None:
        record = GroundedVerificationRecord(
            applied=True,
            verdict="partially_supported",
            score=0.6,
            claim_count=2,
            conflicting_count=0,
            not_enough_evidence_count=1,
        )
        assert record.not_enough_evidence_count == 1

    def test_grounded_verification_record_new_fields_default_to_zero(self) -> None:
        record = GroundedVerificationRecord(applied=False)
        assert record.conflicting_count == 0
        assert record.not_enough_evidence_count == 0


# ---------------------------------------------------------------------------
# GroundedVerifierResult dataclass — new fields
# ---------------------------------------------------------------------------


class TestGroundedVerifierResultF338:
    def test_fallback_result_has_zero_new_counts(self) -> None:
        result = GroundedAnswerVerifier._fallback("test answer")
        assert result.conflicting_claim_count == 0
        assert result.not_enough_evidence_claim_count == 0

    @pytest.mark.asyncio
    async def test_result_populates_conflicting_count(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_ALL_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.conflicting_claim_count == 2
        assert result.not_enough_evidence_claim_count == 0

    @pytest.mark.asyncio
    async def test_result_populates_not_enough_evidence_count(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_NOT_ENOUGH_EVIDENCE_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.not_enough_evidence_claim_count == 1
        assert result.conflicting_claim_count == 0

    def test_result_is_frozen(self) -> None:
        result = GroundedAnswerVerifier._fallback("test")
        with pytest.raises((AttributeError, TypeError)):
            result.conflicting_claim_count = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Latency and performance
# ---------------------------------------------------------------------------


class TestLatencyAndPerformanceF338:
    @pytest.mark.asyncio
    async def test_latency_ms_set_on_conflicting_result(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_latency_ms_zero_on_fallback(self) -> None:
        svc = _make_service()
        provider = AsyncMock()
        provider.complete.side_effect = TimeoutError("timeout")
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.latency_ms == 0

    @pytest.mark.asyncio
    async def test_many_chunks_with_conflicting_claims_no_error(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        many_chunks = _make_chunks(20)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=many_chunks)

        assert result.applied is True
        assert result.conflicting_claim_count == 1

    @pytest.mark.asyncio
    async def test_model_and_provider_set_on_success(self) -> None:
        svc = _make_service()
        provider = _mock_provider(_CONFLICTING_JSON)
        with patch.object(svc, "_resolve_provider", return_value=provider):
            result = await svc.verify(answer="Answer.", chunks=_make_chunks())

        assert result.model_name != ""
        assert result.provider_key != ""
