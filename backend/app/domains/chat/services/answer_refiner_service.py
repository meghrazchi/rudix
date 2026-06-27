"""Answer refiner (F339).

Rewrites the draft answer using only claims supported by validated citations,
guided by the critic's plain-English instructions. This is the final safety
gate before high-risk answers are shown to users.

Design constraints:
- Citation text snippets (already stored by citation validation) are the only
  source data passed to the LLM. Raw retrieved chunk text is NEVER stored in
  RefinerResult or passed beyond this service's internal LLM prompt.
- On any LLM or parse failure the service returns the original draft answer
  unchanged (applied=False) so the caller can proceed safely.
- The refiner is only called when AnswerCriticService.requires_refiner is True.
- If the refined answer is empty the caller should treat it as not_found.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from time import perf_counter

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.domains.ai.providers.protocols import ChatCompletionRequest

logger = logging.getLogger("chat.answer_refiner")

_MAX_ANSWER_CHARS = 4000
_MAX_SNIPPET_CHARS = 400
_MAX_CHANGE_CHARS = 150
_MAX_CHANGES = 5


# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------


class _RefinerOutput(BaseModel):
    """Structured JSON the LLM returns after one refinement pass."""

    refined_answer: str = Field(default="", max_length=_MAX_ANSWER_CHARS)
    changes_made: list[str] = Field(default_factory=list)
    unsupported_claims_removed: int = Field(default=0, ge=0)

    @field_validator("changes_made", mode="before")
    @classmethod
    def _clean_changes(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return []
        return [
            str(item).strip()[:_MAX_CHANGE_CHARS]
            for item in v
            if str(item).strip()
        ][:_MAX_CHANGES]

    @classmethod
    def parse(cls, raw: str) -> "_RefinerOutput":
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object in refiner LLM output")
        return cls.model_validate(json.loads(raw[start : end + 1]))


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an answer refiner for an enterprise document retrieval system.
Your job: rewrite a DRAFT ANSWER so that it contains only claims directly \
supported by the VALIDATED CITATIONS, guided by the CRITIC INSTRUCTIONS below.

Steps:
1. Read the CRITIC INSTRUCTIONS — they describe specific quality problems to fix.
2. Read the DRAFT ANSWER carefully.
3. Read the VALIDATED CITATIONS — these are the only trusted sources you may use.
4. Rewrite the answer, applying these rules:
   - Keep only factual claims that are directly supported by the citations.
   - Follow the CRITIC INSTRUCTIONS for each issue type.
   - Preserve the original answer's language and structure where possible.
   - If no claims can be supported, return an empty string for refined_answer.

Return a single JSON object with:
  "refined_answer": the rewritten answer text. Use "" if no claims are supportable.
  "changes_made": list of brief (≤150 chars) descriptions of changes made.
    Maximum 5 items. NEVER quote raw source text here.
  "unsupported_claims_removed": integer — count of claims removed.

Return ONLY valid JSON. No markdown fences, no text outside the JSON object.
Never reveal, quote, or embed raw SOURCE CHUNK text in changes_made.
"""


def _build_refiner_prompt(
    *,
    draft_answer: str,
    critic_instruction: str,
    citation_snippets: list[str],
) -> str:
    citation_block = "\n\n".join(
        f"[CITATION {i}]\n{snippet[:_MAX_SNIPPET_CHARS].strip()}"
        for i, snippet in enumerate(citation_snippets, 1)
    )
    return (
        f"{_SYSTEM_PROMPT}\n\n"
        f"CRITIC INSTRUCTIONS:\n{critic_instruction}\n\n"
        f"DRAFT ANSWER:\n{draft_answer[:_MAX_ANSWER_CHARS].strip()}\n\n"
        f"VALIDATED CITATIONS:\n{citation_block or '<none>'}"
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefinerResult:
    """Output of one answer refinement pass.

    Callers should:
    - Use `refined_answer` as the final answer when `applied` is True and
      `refined_answer` is non-empty.
    - Treat an empty `refined_answer` (with applied=True) as not_found.
    - Use `draft_changed` and `unsupported_claims_removed` for trust metadata.
    - Never store or log raw chunk text obtained via the refiner path.
    """

    applied: bool
    draft_changed: bool
    refined_answer: str
    changes_made: list[str] = field(default_factory=list)
    unsupported_claims_removed: int = 0
    model_name: str = ""
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AnswerRefinerService:
    """LLM-backed answer refiner.

    Rewrites the draft answer using only claims directly supported by the
    validated citation snippets, guided by the critic's structured instruction.

    On any LLM or parse error the original draft answer is returned unchanged
    (applied=False) so the caller can present it without blocking.
    """

    def __init__(self, *, timeout_seconds: float | None = None) -> None:
        self._timeout_seconds = timeout_seconds or settings.refiner_timeout_seconds

    def _resolve_provider(self):  # type: ignore[return]
        from app.domains.ai.providers.factory import default_provider_factory

        return default_provider_factory.get_chat_provider()

    @staticmethod
    def _fallback(answer: str) -> RefinerResult:
        return RefinerResult(
            applied=False,
            draft_changed=False,
            refined_answer=answer,
            changes_made=[],
            unsupported_claims_removed=0,
        )

    async def refine(
        self,
        *,
        draft_answer: str,
        critic_instruction: str,
        citation_snippets: list[str],
    ) -> RefinerResult:
        """Refine the draft answer according to critic instructions.

        Args:
            draft_answer: The LLM-generated draft answer to refine.
            critic_instruction: Plain-English instructions from the critic on
                what specific quality issues to address.
            citation_snippets: Short text excerpts from validated citations
                (text_snippet field, ≤400 chars each, max 10). These are the
                only sources the refiner's LLM prompt draws on. Raw chunk text
                must NOT be passed here.
        """
        if not draft_answer.strip():
            return self._fallback(draft_answer)

        started = perf_counter()
        try:
            provider = self._resolve_provider()
            prompt = _build_refiner_prompt(
                draft_answer=draft_answer,
                critic_instruction=critic_instruction,
                citation_snippets=citation_snippets[:10],
            )
            request = ChatCompletionRequest(
                prompt=prompt,
                model=settings.openai_llm_model,
                temperature=0.0,
                json_mode=True,
            )
            response = await provider.complete(request)
            raw_text = response.content or ""
            parsed = _RefinerOutput.parse(raw_text)
        except Exception as exc:
            logger.warning("answer_refiner failed, using original answer: %s", exc)
            return self._fallback(draft_answer)

        latency_ms = int((perf_counter() - started) * 1000)
        refined = parsed.refined_answer.strip()

        logger.debug(
            "answer_refiner applied=%s draft_changed=%s removed=%d latency_ms=%d",
            True,
            refined != draft_answer.strip(),
            parsed.unsupported_claims_removed,
            latency_ms,
        )

        return RefinerResult(
            applied=True,
            draft_changed=refined != draft_answer.strip(),
            refined_answer=refined,
            changes_made=list(parsed.changes_made),
            unsupported_claims_removed=parsed.unsupported_claims_removed,
            model_name=settings.openai_llm_model,
            latency_ms=latency_ms,
        )
