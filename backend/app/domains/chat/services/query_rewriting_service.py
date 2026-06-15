"""Query rewriting and question decomposition service (F295).

Improves retrieval accuracy by:
- Rewriting vague questions to expand acronyms, synonyms, and entities.
- Decomposing multi-part questions into focused sub-queries for independent retrieval.

Design constraints:
- Scope filters (document_ids, collection scope, org tenancy) are applied downstream
  in the retrieval layer and are never touched here — rewriting cannot bypass them.
- On any LLM or parse failure, the service returns the original query (safe fallback).
- Sub-query count is capped at max_sub_queries to bound retrieval cost and latency.
- The original user question is always returned unchanged in `original_query` and
  must be used for the final LLM answer prompt (intent preservation).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import settings
from app.domains.ai.providers.protocols import ChatCompletionRequest

logger = logging.getLogger("chat.query_rewriting")

# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------

_MAX_QUERY_LEN = 1000
_STRATEGY_VALUES: frozenset[str] = frozenset({"original", "rewrite", "decompose"})


class _RewritingOutput(BaseModel):
    """Structured JSON the LLM returns for one user question."""

    strategy: Literal["original", "rewrite", "decompose"]
    primary_query: str = Field(min_length=1, max_length=_MAX_QUERY_LEN)
    sub_queries: list[str] = Field(default_factory=list)

    @field_validator("primary_query")
    @classmethod
    def _strip_primary(cls, v: str) -> str:
        return v.strip()

    @field_validator("sub_queries", mode="before")
    @classmethod
    def _validate_sub_queries(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("sub_queries must be a list")
        cleaned: list[str] = []
        for item in v:
            s = str(item).strip()
            if s:
                cleaned.append(s[:_MAX_QUERY_LEN])
        return cleaned


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryRewritingResult:
    """Output of one rewriting pass over a user question.

    Callers must:
    - Use `primary_query` as the embedding / keyword-search query (single-query path).
    - Use `sub_queries` for parallel retrievals when `decomposition_applied` is True.
    - Always use `original_query` for the final LLM answer prompt.
    """

    original_query: str
    primary_query: str
    sub_queries: list[str] = field(default_factory=list)
    strategy: str = "original"
    rewriting_applied: bool = False
    decomposition_applied: bool = False
    latency_ms: int = 0
    provider_key: str = "openai"
    model_name: str = ""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a search-query optimizer for an enterprise document retrieval system.
Given a user question, choose the best retrieval strategy and return a JSON object.

Strategies:
- "original": The question is already clear, specific, and well-suited for retrieval. Use it unchanged.
- "rewrite": The question contains acronyms, abbreviations, or vague phrasing that can be expanded \
to improve document matching. Return an enriched query in primary_query.
- "decompose": The question has two or more independent parts, each requiring different evidence. \
Return a unified primary_query and individual sub_queries (one per distinct information need).

Constraints:
- Never change the user's intent.
- Never add references to specific documents, collections, or organisational data that are not \
already present in the question.
- Keep sub_queries to at most {max_sub_queries} items.
- Each sub_query must be self-contained (answerable independently from the others).
- primary_query must always be present and non-empty.
- For strategy "original" and "rewrite", sub_queries must be empty ([]).

Return only a single JSON object — no markdown, no explanation:
{{
  "strategy": "original" | "rewrite" | "decompose",
  "primary_query": "<query for retrieval>",
  "sub_queries": []
}}
"""


def _build_prompt(question: str, max_sub_queries: int) -> str:
    system = _SYSTEM_PROMPT.format(max_sub_queries=max_sub_queries)
    return f"{system}\n\nUser question: {question}"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class QueryRewritingService:
    """LLM-backed query rewriting and decomposition service."""

    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        max_sub_queries: int | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds or settings.query_rewriting_timeout_seconds
        self._max_sub_queries = max_sub_queries or settings.query_rewriting_max_sub_queries

    def _resolve_provider(self):  # type: ignore[return]
        from app.domains.ai.providers.factory import default_provider_factory

        return default_provider_factory.get_chat_provider()

    @staticmethod
    def _parse_output(raw: str) -> _RewritingOutput:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No JSON object in LLM output")
        return _RewritingOutput.model_validate(json.loads(raw[start : end + 1]))

    @staticmethod
    def _apply_limits(parsed: _RewritingOutput, *, max_sub_queries: int) -> _RewritingOutput:
        """Cap sub-queries and normalise strategy consistency."""
        sub_queries = parsed.sub_queries[:max_sub_queries]
        strategy = parsed.strategy
        if strategy == "decompose" and not sub_queries:
            strategy = "rewrite"
        if strategy != "decompose":
            sub_queries = []
        return _RewritingOutput(
            strategy=strategy,
            primary_query=parsed.primary_query,
            sub_queries=sub_queries,
        )

    async def rewrite(
        self,
        question: str,
        *,
        profile_rewriting_enabled: bool = True,
        profile_decomposition_enabled: bool = True,
        max_sub_queries: int | None = None,
    ) -> QueryRewritingResult:
        """Rewrite / decompose *question* for better retrieval.

        Always returns a valid `QueryRewritingResult` — falls back to the
        original question on any error so the caller can proceed safely.
        """
        if not question.strip():
            return self._fallback(question)

        effective_max = max_sub_queries or self._max_sub_queries
        if not profile_decomposition_enabled:
            # When decomposition is off, cap at 0 to force rewrite-or-original only.
            effective_max = 0

        started = perf_counter()
        try:
            provider = self._resolve_provider()
            prompt = _build_prompt(question, effective_max)
            request = ChatCompletionRequest(
                prompt=prompt,
                model=settings.openai_llm_model,
                temperature=0.0,
                json_mode=True,
            )
            response = await provider.complete(request)
            raw_text = response.content or ""
            parsed = self._parse_output(raw_text)
            parsed = self._apply_limits(parsed, max_sub_queries=effective_max)

            if not profile_rewriting_enabled and parsed.strategy == "rewrite":
                parsed = _RewritingOutput(
                    strategy="original",
                    primary_query=question,
                    sub_queries=[],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("query_rewriting failed, using original query: %s", exc)
            return self._fallback(question)

        latency_ms = int((perf_counter() - started) * 1000)
        strategy = parsed.strategy
        primary_query = parsed.primary_query if strategy != "original" else question
        sub_queries = list(parsed.sub_queries)
        rewriting_applied = strategy in {"rewrite", "decompose"} and primary_query != question
        decomposition_applied = strategy == "decompose" and bool(sub_queries)

        logger.debug(
            "query_rewriting strategy=%s rewriting=%s decompose=%s latency_ms=%d",
            strategy,
            rewriting_applied,
            decomposition_applied,
            latency_ms,
        )

        provider_key = settings.llm_default_provider
        model_name = settings.openai_llm_model

        return QueryRewritingResult(
            original_query=question,
            primary_query=primary_query,
            sub_queries=sub_queries,
            strategy=strategy,
            rewriting_applied=rewriting_applied,
            decomposition_applied=decomposition_applied,
            latency_ms=latency_ms,
            provider_key=provider_key,
            model_name=model_name,
        )

    @staticmethod
    def _fallback(question: str) -> QueryRewritingResult:
        return QueryRewritingResult(
            original_query=question,
            primary_query=question,
            sub_queries=[],
            strategy="original",
            rewriting_applied=False,
            decomposition_applied=False,
            latency_ms=0,
        )
