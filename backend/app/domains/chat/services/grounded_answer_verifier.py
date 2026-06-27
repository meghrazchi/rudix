"""Grounded-answer verifier (F296).

Validates that generated answers are supported by retrieved source chunks.
Unsupported claims are removed in the revised answer (standard mode) or the whole
answer is refused (strict mode when verdict is "unsupported").

Design constraints:
- Raw chunk text is fed only to the LLM prompt and is NEVER stored or returned
  in the result (no source-text leakage through the verifier path).
- On any LLM or parse failure, the service returns a safe fallback
  (verdict=supported, original answer unchanged) so the caller can proceed.
- Verifier is skipped when answer is already a not_found signal or chunks are empty.
- All chunk context is org-scoped; no cross-org data can reach the verifier.
- removed_claims contains short excerpts from the ANSWER only, not from sources.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.domains.ai.providers.protocols import ChatCompletionRequest

logger = logging.getLogger("chat.grounded_verifier")

_MAX_CHUNK_CHARS = 1200
_MAX_CITATION_SNIPPET_CHARS = 400
_MAX_ANSWER_CHARS = 4000
_MAX_REMOVED_CLAIM_CHARS = 200
_MAX_REASON_CODE_CHARS = 64
_ALLOWED_REASON_CODES: frozenset[str] = frozenset(
    {
        "no_source",
        "contradicts_context",
        "out_of_scope",
        "low_coverage",
        "hallucinated_detail",
        "ambiguous",
        "source_conflict",
        "insufficient_evidence",
    }
)


# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------


class _VerifierOutput(BaseModel):
    """Structured JSON the LLM returns for one verification pass."""

    verdict: Literal["supported", "partially_supported", "unsupported"]
    revised_answer: str = Field(default="", max_length=_MAX_ANSWER_CHARS)
    removed_claims: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    claim_count: int = Field(default=0, ge=0)
    supported_claim_count: int = Field(default=0, ge=0)
    partially_supported_claim_count: int = Field(default=0, ge=0)
    unsupported_claim_count: int = Field(default=0, ge=0)
    unverifiable_claim_count: int = Field(default=0, ge=0)
    conflicting_claim_count: int = Field(default=0, ge=0)
    not_enough_evidence_claim_count: int = Field(default=0, ge=0)
    claims: list[_VerifierClaimOutput] = Field(default_factory=list)

    @field_validator("removed_claims", mode="before")
    @classmethod
    def _clean_removed(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(item).strip()[:_MAX_REMOVED_CLAIM_CHARS] for item in v if str(item).strip()][
            :10
        ]

    @field_validator("reason_codes", mode="before")
    @classmethod
    def _clean_reason_codes(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return []
        return [
            str(item).strip()[:_MAX_REASON_CODE_CHARS]
            for item in v
            if str(item).strip() in _ALLOWED_REASON_CODES
        ][:6]


class _VerifierClaimCitationRef(BaseModel):
    """A 1-based citation index returned by the verifier."""

    citation_index: int = Field(ge=1)


class _VerifierClaimOutput(BaseModel):
    """Structured claim-level evidence returned by the verifier."""

    claim_text: str = Field(min_length=1, max_length=600)
    support_status: Literal[
        "supported",
        "partially_supported",
        "unsupported",
        "unverifiable",
        "conflicting",
        "not_enough_evidence",
    ]
    citation_indices: list[_VerifierClaimCitationRef] = Field(default_factory=list)

    @field_validator("citation_indices", mode="before")
    @classmethod
    def _clean_citation_indices(cls, value: object) -> list[dict[str, int]]:
        if not isinstance(value, list):
            return []
        cleaned: list[dict[str, int]] = []
        seen: set[int] = set()
        for item in value:
            try:
                citation_index = (
                    int(item["citation_index"]) if isinstance(item, dict) else int(item)
                )
            except (KeyError, TypeError, ValueError):
                continue
            if citation_index < 1 or citation_index in seen:
                continue
            seen.add(citation_index)
            cleaned.append({"citation_index": citation_index})
        return cleaned


_VerifierOutput.model_rebuild()


# ---------------------------------------------------------------------------
# Public input / result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifierChunk:
    """Minimal chunk representation passed into the verifier.

    Only text is forwarded to the LLM prompt; chunk_id is kept for
    audit purposes but never surfaces in the result.
    """

    chunk_id: str
    text: str
    similarity_score: float = 0.0


@dataclass(frozen=True)
class VerifierCitation:
    """Validated citation evidence passed to the grounded verifier."""

    document_id: str
    chunk_id: str
    filename: str
    page_number: int | None
    text_snippet: str
    score: float = 0.0
    similarity_score: float = 0.0
    rerank_score: float | None = None
    source_trust_status: str | None = None
    doc_ocr_quality_status: str | None = None
    doc_ocr_low_confidence_warning: bool = False
    doc_stale_warning: bool = False
    doc_expired_warning: bool = False
    doc_is_excluded_status: bool = False


@dataclass(frozen=True)
class GroundedVerifierResult:
    """Output of one grounded-answer verification pass.

    Callers must:
    - Use `final_answer` instead of the raw LLM answer when `applied` is True.
    - Treat verdict="unsupported" in strict mode as a not_found signal.
    - Treat conflicting_claim_count > 0 as a verification_failed signal.
    - Never store or log raw chunk text obtained via the verifier path.
    """

    applied: bool
    verdict: str  # "supported" | "partially_supported" | "unsupported"
    verification_score: float  # fraction of claims that are supported (0–1)
    claim_count: int
    supported_claim_count: int
    partially_supported_claim_count: int
    unsupported_claim_count: int
    unverifiable_claim_count: int
    conflicting_claim_count: int = 0
    not_enough_evidence_claim_count: int = 0
    removed_claims: list[str] = field(default_factory=list)  # answer excerpts only
    reason_codes: list[str] = field(default_factory=list)
    claims: list[GroundedClaimResult] = field(default_factory=list)
    aggregate_support_score: float = 0.0
    final_answer: str = ""
    model_name: str = ""
    provider_key: str = ""
    latency_ms: int = 0
    mode: str = "standard"
    threshold: float = 0.7


@dataclass(frozen=True)
class GroundedClaimResult:
    """Claim-level evidence mapping returned by the verifier."""

    claim_text: str
    support_status: Literal[
        "supported",
        "partially_supported",
        "unsupported",
        "unverifiable",
        "conflicting",
        "not_enough_evidence",
    ]
    support_score: float
    evidence_match_score: float
    source_quality_score: float
    rerank_score: float
    chunk_coverage_score: float
    citation_indices: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a grounded-answer fact-checker for an enterprise document retrieval system.
Your job: verify that every factual claim in the GENERATED ANSWER is directly supported \
by the provided SOURCE CHUNKS.

Steps:
1. Read all SOURCE CHUNKS carefully.
2. Read the GENERATED ANSWER carefully.
3. Identify factual claims (sentences that make verifiable assertions).
4. For each claim, decide if a SOURCE CHUNK explicitly supports it.
5. Return a single JSON object with these fields:

  "verdict": one of "supported" | "partially_supported" | "unsupported"
    - "supported": all (or nearly all) claims are backed by the sources.
    - "partially_supported": some claims are backed, some are not.
    - "unsupported": the majority of claims have no source support.

  "revised_answer": the answer text with unsupported claims removed.
    - If verdict is "supported", copy the original answer VERBATIM.
    - If verdict is "unsupported", return an empty string "".
    - For "partially_supported", keep only the supported sentences.

  "removed_claims": list of SHORT plain-text descriptions of removed claims.
    Maximum 200 characters each, maximum 10 items.
    NEVER quote raw source text here — only summarise what was removed.

  "claim_count": integer — total factual claims identified.
  "supported_claim_count": integer — claims with direct source support.
  "partially_supported_claim_count": integer — claims with some support but
    needing rewrite.
  "unsupported_claim_count": integer — claims with no source support.
  "unverifiable_claim_count": integer — claims the sources do not let you verify.
  "conflicting_claim_count": integer — claims where retrieved sources actively
    contradict each other about the claim (e.g. source A says X, source B says NOT X).
  "not_enough_evidence_claim_count": integer — claims where sources touch the topic
    but provide insufficient detail to confirm or deny the claim.

  "claims": list of claim objects. Each claim object must include:
    - claim_text: a short excerpt or normalized sentence from the answer
    - support_status: supported | partially_supported | unsupported | unverifiable
        | conflicting | not_enough_evidence
      Use "conflicting" when multiple retrieved sources directly contradict each other
      about this specific claim. Use "not_enough_evidence" when sources are relevant
      but lack the detail needed to verify — distinct from "unsupported" (no source
      at all) and "unverifiable" (topic out of scope for any source).
    - citation_indices: 1-based indices into VALIDATED CITATIONS
      A claim may reference multiple citations when several chunks support it.

  "reason_codes": list of reason codes from this set only:
    ["no_source", "contradicts_context", "out_of_scope",
     "low_coverage", "hallucinated_detail", "ambiguous",
     "source_conflict", "insufficient_evidence"]

Constraints:
- Return ONLY valid JSON — no markdown fences, no explanation outside the JSON.
- Never reveal, quote, or embed raw SOURCE CHUNK text in removed_claims.
- claim_count = supported_claim_count + partially_supported_claim_count +
  unsupported_claim_count + unverifiable_claim_count.
"""


def _evidence_match_score(status: str) -> float:
    if status == "supported":
        return 1.0
    if status == "partially_supported":
        return 0.65
    if status == "not_enough_evidence":
        return 0.2
    if status == "unverifiable":
        return 0.3
    # "conflicting" and "unsupported" both score 0 — conflicting is actively contradicted
    return 0.0


def _source_trust_score(status: str | None) -> float:
    if status == "trusted":
        return 1.0
    if status == "uploaded":
        return 0.9
    if status in {"unknown", None}:
        return 0.75
    if status == "stale":
        return 0.55
    if status == "revoked":
        return 0.2
    if status == "deleted":
        return 0.0
    return 0.75


def _ocr_quality_multiplier(quality: str | None, low_confidence_warning: bool) -> float:
    if low_confidence_warning:
        return 0.82
    if quality == "high" or quality == "not_required" or quality is None:
        return 1.0
    if quality == "medium":
        return 0.92
    if quality == "low":
        return 0.75
    if quality == "failed":
        return 0.5
    return 0.9


def _citation_support_quality(citation: VerifierCitation) -> float:
    trust_score = _source_trust_score(citation.source_trust_status)
    quality_multiplier = _ocr_quality_multiplier(
        citation.doc_ocr_quality_status,
        citation.doc_ocr_low_confidence_warning,
    )
    freshness_multiplier = 1.0
    if citation.doc_is_excluded_status:
        freshness_multiplier *= 0.1
    if citation.doc_expired_warning:
        freshness_multiplier *= 0.45
    elif citation.doc_stale_warning:
        freshness_multiplier *= 0.75
    return max(0.0, min(1.0, round(trust_score * quality_multiplier * freshness_multiplier, 4)))


def _claim_support_score(
    *,
    status: str,
    citation_indices: list[int],
    citations: list[VerifierCitation],
) -> tuple[float, float, float, float]:
    evidence_match_score = _evidence_match_score(status)
    valid_indices = [idx for idx in citation_indices if 1 <= idx <= len(citations)]
    if not valid_indices:
        return evidence_match_score, 0.0, 0.0, 0.0

    referenced_citations = [citations[idx - 1] for idx in valid_indices]
    source_quality_score = sum(_citation_support_quality(c) for c in referenced_citations) / len(
        referenced_citations
    )
    rerank_values = [
        c.rerank_score if c.rerank_score is not None else c.score for c in referenced_citations
    ]
    rerank_score = sum(max(0.0, min(1.0, value)) for value in rerank_values) / len(rerank_values)
    chunk_coverage_score = min(1.0, len({c.chunk_id for c in referenced_citations}) / 2.0)
    support_score = (
        (0.45 * evidence_match_score)
        + (0.25 * source_quality_score)
        + (0.2 * rerank_score)
        + (0.1 * chunk_coverage_score)
    )
    return (
        round(max(0.0, min(1.0, support_score)), 4),
        round(source_quality_score, 4),
        round(rerank_score, 4),
        round(chunk_coverage_score, 4),
    )


def _build_verifier_prompt(
    answer: str,
    chunks: list[VerifierChunk],
    citations: list[VerifierCitation],
) -> str:
    chunk_sections = "\n\n".join(
        f"[SOURCE {i}]\n{chunk.text[:_MAX_CHUNK_CHARS].strip()}"
        for i, chunk in enumerate(chunks, 1)
    )
    citation_sections = "\n\n".join(
        f"[CITATION {i}]\n"
        f"document_id={citation.document_id}\n"
        f"chunk_id={citation.chunk_id}\n"
        f"filename={citation.filename}\n"
        f"page_number={citation.page_number}\n"
        f"score={citation.score}\n"
        f"text_snippet={citation.text_snippet[:_MAX_CITATION_SNIPPET_CHARS].strip()}"
        for i, citation in enumerate(citations, 1)
    )
    answer_block = answer[:_MAX_ANSWER_CHARS].strip()
    return (
        f"{_SYSTEM_PROMPT}\n\nSOURCE CHUNKS:\n{chunk_sections}\n\nGENERATED ANSWER:\n{answer_block}"
        + (
            f"\n\nVALIDATED CITATIONS:\n{citation_sections}"
            if citation_sections
            else "\n\nVALIDATED CITATIONS:\n<none>"
        )
    )


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GroundedAnswerVerifier:
    """LLM-backed grounded-answer verifier.

    Validates that each factual claim in the generated answer is supported
    by the retrieved source chunks. Unsupported claims are removed in the
    revised answer; in strict mode a fully unsupported answer is blanked so
    the caller can substitute a not_found response.

    On any error the service returns a safe fallback (verdict=supported,
    original answer unchanged) so the caller never blocks on verifier failure.
    """

    def __init__(self, *, timeout_seconds: float | None = None) -> None:
        self._timeout_seconds = timeout_seconds or settings.grounded_verification_timeout_seconds

    def _resolve_provider(self):  # type: ignore[return]
        from app.domains.ai.providers.factory import default_provider_factory

        return default_provider_factory.get_chat_provider()

    @staticmethod
    def _parse_output(raw: str) -> _VerifierOutput:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object in LLM output")
        return _VerifierOutput.model_validate(json.loads(raw[start : end + 1]))

    @staticmethod
    def _fallback(
        answer: str,
        *,
        mode: str = "standard",
        threshold: float = 0.7,
    ) -> GroundedVerifierResult:
        return GroundedVerifierResult(
            applied=False,
            verdict="supported",
            verification_score=1.0,
            claim_count=0,
            supported_claim_count=0,
            partially_supported_claim_count=0,
            unsupported_claim_count=0,
            unverifiable_claim_count=0,
            conflicting_claim_count=0,
            not_enough_evidence_claim_count=0,
            removed_claims=[],
            reason_codes=[],
            final_answer=answer,
            model_name="",
            provider_key="",
            latency_ms=0,
            mode=mode,
            threshold=threshold,
        )

    async def verify(
        self,
        *,
        answer: str,
        chunks: list[VerifierChunk],
        citations: list[VerifierCitation] | None = None,
        mode: Literal["strict", "standard"] = "standard",
        threshold: float = 0.7,
    ) -> GroundedVerifierResult:
        """Verify that `answer` is grounded in `chunks`.

        Always returns a valid `GroundedVerifierResult` — falls back to the
        original answer (verdict=supported) on any error so the caller can
        proceed safely.

        Args:
            answer: The generated answer to verify.
            chunks: Source chunks that were retrieved for this query.
            mode: "strict" treats a fully unsupported answer as not_found;
                  "standard" only removes individual unsupported claims.
            threshold: Minimum verification_score to consider answer supported
                       (informational — caller decides how to use it).
        """
        if not answer.strip() or not chunks:
            return self._fallback(answer, mode=mode, threshold=threshold)

        started = perf_counter()
        try:
            provider = self._resolve_provider()
            prompt = _build_verifier_prompt(answer, chunks, citations or [])
            request = ChatCompletionRequest(
                prompt=prompt,
                model=settings.openai_llm_model,
                temperature=0.0,
                json_mode=True,
            )
            response = await provider.complete(request)
            raw_text = response.content or ""
            parsed = self._parse_output(raw_text)
        except Exception as exc:
            logger.warning("grounded_verifier failed, using original answer: %s", exc)
            return self._fallback(answer, mode=mode, threshold=threshold)

        latency_ms = int((perf_counter() - started) * 1000)

        counted_claims = (
            parsed.supported_claim_count
            + parsed.partially_supported_claim_count
            + parsed.unsupported_claim_count
            + parsed.unverifiable_claim_count
            + parsed.conflicting_claim_count
            + parsed.not_enough_evidence_claim_count
        )
        total = max(1, parsed.claim_count or counted_claims)
        if counted_claims and counted_claims != parsed.claim_count:
            total = counted_claims
        # conflicting = 0 weight (actively contradicted, same as unsupported)
        # not_enough_evidence = 0.2 weight (partial signal, slightly above unsupported)
        weighted_supported = (
            parsed.supported_claim_count
            + (0.5 * parsed.partially_supported_claim_count)
            + (0.2 * parsed.not_enough_evidence_claim_count)
        )
        verification_score = round(weighted_supported / total, 4)

        final_answer = parsed.revised_answer.strip()
        if not final_answer and parsed.verdict == "supported":
            final_answer = answer
        if parsed.verdict == "unsupported":
            final_answer = ""

        grounded_claims: list[GroundedClaimResult] = []
        for claim in list(parsed.claims)[:50]:
            citation_indices = [ref.citation_index for ref in claim.citation_indices]
            (
                support_score,
                source_quality_score,
                rerank_score,
                chunk_coverage_score,
            ) = _claim_support_score(
                status=claim.support_status,
                citation_indices=citation_indices,
                citations=list(citations or []),
            )
            grounded_claims.append(
                GroundedClaimResult(
                    claim_text=claim.claim_text.strip()[:600],
                    support_status=claim.support_status,
                    support_score=support_score,
                    evidence_match_score=_evidence_match_score(claim.support_status),
                    source_quality_score=source_quality_score,
                    rerank_score=rerank_score,
                    chunk_coverage_score=chunk_coverage_score,
                    citation_indices=[
                        idx for idx in citation_indices if 1 <= idx <= len(citations or [])
                    ],
                )
            )

        aggregate_support_score = (
            round(
                sum(claim.support_score for claim in grounded_claims) / len(grounded_claims),
                4,
            )
            if grounded_claims
            else verification_score
        )

        # In strict mode, insufficient or conflicting evidence is treated as not_found
        # so the caller can safely refuse rather than showing a misleading answer.
        strict_refusal = mode == "strict" and (
            parsed.verdict == "unsupported"
            or verification_score < threshold
            or parsed.conflicting_claim_count > 0
        )
        if strict_refusal:
            final_answer = ""

        logger.debug(
            "grounded_verifier verdict=%s score=%.3f claims=%d unsupported=%d latency_ms=%d",
            parsed.verdict,
            verification_score,
            parsed.claim_count,
            parsed.unsupported_claim_count,
            latency_ms,
        )

        return GroundedVerifierResult(
            applied=True,
            verdict=parsed.verdict,
            verification_score=verification_score,
            claim_count=parsed.claim_count,
            supported_claim_count=parsed.supported_claim_count,
            partially_supported_claim_count=parsed.partially_supported_claim_count,
            unsupported_claim_count=parsed.unsupported_claim_count,
            unverifiable_claim_count=parsed.unverifiable_claim_count,
            conflicting_claim_count=parsed.conflicting_claim_count,
            not_enough_evidence_claim_count=parsed.not_enough_evidence_claim_count,
            removed_claims=list(parsed.removed_claims),
            reason_codes=list(parsed.reason_codes),
            claims=grounded_claims,
            aggregate_support_score=aggregate_support_score,
            final_answer=final_answer,
            model_name=settings.openai_llm_model,
            provider_key=settings.llm_default_provider,
            latency_ms=latency_ms,
            mode=mode,
            threshold=threshold,
        )
