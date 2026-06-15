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
    unsupported_claim_count: int = Field(default=0, ge=0)

    @field_validator("removed_claims", mode="before")
    @classmethod
    def _clean_removed(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return []
        return [
            str(item).strip()[:_MAX_REMOVED_CLAIM_CHARS]
            for item in v
            if str(item).strip()
        ][:10]

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
class GroundedVerifierResult:
    """Output of one grounded-answer verification pass.

    Callers must:
    - Use `final_answer` instead of the raw LLM answer when `applied` is True.
    - Treat verdict="unsupported" in strict mode as a not_found signal.
    - Never store or log raw chunk text obtained via the verifier path.
    """

    applied: bool
    verdict: str  # "supported" | "partially_supported" | "unsupported"
    verification_score: float  # fraction of claims that are supported (0–1)
    claim_count: int
    supported_claim_count: int
    unsupported_claim_count: int
    removed_claims: list[str] = field(default_factory=list)  # answer excerpts only
    reason_codes: list[str] = field(default_factory=list)
    final_answer: str = ""
    model_name: str = ""
    provider_key: str = ""
    latency_ms: int = 0


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

  "reason_codes": list of reason codes from this set only:
    ["no_source", "contradicts_context", "out_of_scope",
     "low_coverage", "hallucinated_detail", "ambiguous"]

  "claim_count": integer — total factual claims identified.
  "supported_claim_count": integer — claims with source support.
  "unsupported_claim_count": integer — claims without source support.

Constraints:
- Return ONLY valid JSON — no markdown fences, no explanation outside the JSON.
- Never reveal, quote, or embed raw SOURCE CHUNK text in removed_claims.
- claim_count = supported_claim_count + unsupported_claim_count.
"""


def _build_verifier_prompt(answer: str, chunks: list[VerifierChunk]) -> str:
    chunk_sections = "\n\n".join(
        f"[SOURCE {i}]\n{chunk.text[:_MAX_CHUNK_CHARS].strip()}"
        for i, chunk in enumerate(chunks, 1)
    )
    answer_block = answer[:_MAX_ANSWER_CHARS].strip()
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"SOURCE CHUNKS:\n{chunk_sections}\n\n"
        f"GENERATED ANSWER:\n{answer_block}"
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
        self._timeout_seconds = (
            timeout_seconds or settings.grounded_verification_timeout_seconds
        )

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
    def _fallback(answer: str) -> GroundedVerifierResult:
        return GroundedVerifierResult(
            applied=False,
            verdict="supported",
            verification_score=1.0,
            claim_count=0,
            supported_claim_count=0,
            unsupported_claim_count=0,
            removed_claims=[],
            reason_codes=[],
            final_answer=answer,
            model_name="",
            provider_key="",
            latency_ms=0,
        )

    async def verify(
        self,
        *,
        answer: str,
        chunks: list[VerifierChunk],
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
            return self._fallback(answer)

        started = perf_counter()
        try:
            provider = self._resolve_provider()
            prompt = _build_verifier_prompt(answer, chunks)
            request = ChatCompletionRequest(
                prompt=prompt,
                model=settings.openai_llm_model,
                temperature=0.0,
                json_mode=True,
            )
            response = await provider.complete(request)
            raw_text = response.content or ""
            parsed = self._parse_output(raw_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("grounded_verifier failed, using original answer: %s", exc)
            return self._fallback(answer)

        latency_ms = int((perf_counter() - started) * 1000)

        total = max(1, parsed.claim_count)
        verification_score = round(parsed.supported_claim_count / total, 4)

        # Use revised_answer when non-empty; otherwise fall back to the original
        # so the caller never receives an empty answer unexpectedly.
        final_answer = parsed.revised_answer.strip() or answer

        # In strict mode, a fully unsupported answer is blanked so the caller
        # can substitute a not_found response.
        if mode == "strict" and parsed.verdict == "unsupported":
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
            unsupported_claim_count=parsed.unsupported_claim_count,
            removed_claims=list(parsed.removed_claims),
            reason_codes=list(parsed.reason_codes),
            final_answer=final_answer,
            model_name=settings.openai_llm_model,
            provider_key=settings.llm_default_provider,
            latency_ms=latency_ms,
        )
