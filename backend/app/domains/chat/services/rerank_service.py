from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.ai.providers.errors import (
    ProviderInternalError,
    ProviderQuotaExceededError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedCapabilityError,
)
from app.domains.ai.providers.protocols import ChatCompletionProvider, ChatCompletionRequest

logger = get_logger("chat.rerank")

RerankFallbackBehavior = Literal["original", "disabled"]

_TRANSIENT_PROVIDER_ERRORS = (
    ProviderTimeoutError,
    ProviderQuotaExceededError,
    ProviderUnavailableError,
    ProviderInternalError,
)

_REQUEST_SYSTEM_MESSAGE = (
    "You score relevance for a document retrieval reranker. "
    "Return only valid JSON. Do not add explanations."
)


@dataclass(frozen=True)
class RerankCandidate:
    key: str
    text: str
    similarity_score: float
    original_rank: int | None = None


@dataclass(frozen=True)
class RerankedCandidate:
    key: str
    similarity_score: float
    original_rank: int
    rerank_score: float | None
    rerank_rank: int | None
    final_rank: int


@dataclass(frozen=True)
class RerankDiagnostics:
    enabled: bool
    provider_key: str | None
    model_name: str | None
    requested_count: int
    reranked_count: int
    selected_count: int
    batch_count: int
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    approximate_cost_usd: Decimal
    fallback_used: bool
    fallback_reason: str | None
    timeout_seconds: float | None
    batch_size: int
    max_input_candidates: int
    max_candidate_chars: int


@dataclass(frozen=True)
class RerankResult:
    candidates: list[RerankedCandidate]
    diagnostics: RerankDiagnostics


@dataclass(frozen=True)
class RerankSettings:
    enabled: bool = False
    provider_key: str | None = None
    model_name: str | None = None
    timeout_seconds: float | None = None
    batch_size: int | None = None
    max_input_candidates: int | None = None
    max_candidate_chars: int | None = None
    fallback_behavior: RerankFallbackBehavior = "original"


class _BatchScore(BaseModel):
    key: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)


class _BatchScoreResponse(BaseModel):
    scores: list[_BatchScore] = Field(default_factory=list)


class _ChatCompletionProviderFactory(Protocol):
    def get_chat_provider(self, provider_key: str | None = None) -> ChatCompletionProvider: ...


class RerankService:
    """Provider-backed relevance reranking with safe similarity fallback."""

    def __init__(
        self,
        *,
        provider_factory: _ChatCompletionProviderFactory | None = None,
        default_provider_key: str | None = None,
        default_model_name: str | None = None,
        default_timeout_seconds: float | None = None,
        default_batch_size: int | None = None,
        default_input_candidates: int | None = None,
        default_candidate_chars: int | None = None,
        default_fallback_behavior: RerankFallbackBehavior | None = None,
        mmr_lambda: float | None = None,
        candidate_count: int | None = None,
        duplicate_similarity_threshold: float | None = None,
    ) -> None:
        del mmr_lambda, candidate_count, duplicate_similarity_threshold
        self._provider_factory = provider_factory
        self.default_provider_key = default_provider_key or settings.rerank_default_provider
        self.default_model_name = default_model_name or settings.rerank_default_model_name
        self.default_timeout_seconds = (
            default_timeout_seconds
            if default_timeout_seconds is not None
            else settings.rerank_default_timeout_seconds
        )
        self.default_batch_size = default_batch_size or settings.rerank_default_batch_size
        self.default_input_candidates = (
            default_input_candidates or settings.rerank_default_input_candidates
        )
        self.default_candidate_chars = (
            default_candidate_chars or settings.rerank_default_candidate_chars
        )
        self.default_fallback_behavior = (
            default_fallback_behavior or settings.rerank_default_fallback_behavior
        )
        self.input_cost_per_million_tokens_usd = Decimal(
            str(settings.rerank_input_cost_per_million_tokens_usd)
        )
        self.output_cost_per_million_tokens_usd = Decimal(
            str(settings.rerank_output_cost_per_million_tokens_usd)
        )

    @property
    def candidate_count(self) -> int:
        return self.default_input_candidates

    def _resolve_provider_factory(self) -> _ChatCompletionProviderFactory:
        if self._provider_factory is not None:
            return self._provider_factory
        from app.domains.ai.providers.factory import default_provider_factory

        return default_provider_factory

    @staticmethod
    def _clamp_score(value: float) -> float:
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        normalized = text.strip()
        if len(normalized) <= max_chars:
            return normalized
        return normalized[:max_chars]

    @staticmethod
    def _sorted_original(candidates: list[RerankCandidate]) -> list[RerankCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                -(candidate.similarity_score),
                candidate.original_rank or 0,
                candidate.key,
            ),
        )

    def _build_batch_prompt(self, *, query: str, batch: list[RerankCandidate], max_chars: int) -> str:
        candidate_blocks: list[str] = []
        for candidate in batch:
            candidate_blocks.append(
                "\n".join(
                    [
                        f"key: {candidate.key}",
                        f"original_rank: {candidate.original_rank}",
                        f"similarity_score: {candidate.similarity_score}",
                        "text:",
                        self._truncate_text(candidate.text, max_chars),
                    ]
                )
            )

        examples = (
            "Return JSON with this exact shape:\n"
            '{ "scores": [ { "key": "chunk-1", "score": 0.91 } ] }\n'
            "Scores must be between 0 and 1, where higher means more relevant."
        )
        return (
            "You are reranking retrieved document chunks for a question-answering system.\n"
            "Score each chunk for relevance to the query.\n"
            "Do not invent new keys. Preserve the input chunk keys exactly.\n"
            f"{examples}\n\n"
            f"Query:\n{query.strip()}\n\n"
            "Candidates:\n"
            + "\n\n".join(candidate_blocks)
        )

    @staticmethod
    def _parse_batch_scores(raw_text: str) -> _BatchScoreResponse:
        payload = json.loads(raw_text)
        return _BatchScoreResponse.model_validate(payload)

    async def _score_batch(
        self,
        *,
        query: str,
        batch: list[RerankCandidate],
        provider: ChatCompletionProvider,
        model_name: str,
        timeout_seconds: float | None,
        max_candidate_chars: int,
    ) -> tuple[list[_BatchScore], int, int, int]:
        prompt = self._build_batch_prompt(query=query, batch=batch, max_chars=max_candidate_chars)
        request = ChatCompletionRequest(
            prompt=prompt,
            model=model_name,
            temperature=0.0,
            json_mode=True,
            max_tokens=max(64, len(batch) * 8),
            system_message=_REQUEST_SYSTEM_MESSAGE,
        )

        started = perf_counter()
        response = await asyncio.wait_for(provider.complete(request), timeout=timeout_seconds)
        raw_text = response.content
        if not raw_text:
            raise ValueError("rerank provider returned no content")

        try:
            parsed = self._parse_batch_scores(raw_text)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError("rerank provider returned invalid JSON") from exc

        if len(parsed.scores) != len(batch):
            raise ValueError(
                "rerank provider returned a mismatched number of scores"
            )

        scores_by_key = {item.key: item for item in parsed.scores}
        ordered_scores: list[_BatchScore] = []
        for candidate in batch:
            score = scores_by_key.get(candidate.key)
            if score is None:
                raise ValueError("rerank provider omitted a candidate score")
            ordered_scores.append(score)

        latency_ms = int((perf_counter() - started) * 1000)
        return ordered_scores, response.prompt_tokens, response.completion_tokens, latency_ms

    def _build_fallback_result(
        self,
        *,
        candidates: list[RerankCandidate],
        final_top_k: int,
        diagnostics: RerankDiagnostics,
    ) -> RerankResult:
        selected_candidates = self._sorted_original(candidates)[:final_top_k]
        selected: list[RerankedCandidate] = []
        for index, candidate in enumerate(selected_candidates, start=1):
            selected.append(
                RerankedCandidate(
                    key=candidate.key,
                    similarity_score=self._clamp_score(candidate.similarity_score),
                    original_rank=candidate.original_rank or index,
                    rerank_score=None,
                    rerank_rank=None,
                    final_rank=index,
                )
            )
        return RerankResult(candidates=selected, diagnostics=diagnostics)

    def _build_diagnostics(
        self,
        *,
        enabled: bool,
        provider_key: str | None,
        model_name: str | None,
        requested_count: int,
        reranked_count: int,
        selected_count: int,
        batch_count: int,
        latency_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        fallback_used: bool,
        fallback_reason: str | None,
        timeout_seconds: float | None,
        batch_size: int,
        max_input_candidates: int,
        max_candidate_chars: int,
    ) -> RerankDiagnostics:
        total_tokens = prompt_tokens + completion_tokens
        cost_usd = (
            (Decimal(prompt_tokens) * self.input_cost_per_million_tokens_usd)
            + (Decimal(completion_tokens) * self.output_cost_per_million_tokens_usd)
        ) / Decimal(1_000_000)
        return RerankDiagnostics(
            enabled=enabled,
            provider_key=provider_key,
            model_name=model_name,
            requested_count=requested_count,
            reranked_count=reranked_count,
            selected_count=selected_count,
            batch_count=batch_count,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            approximate_cost_usd=cost_usd,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            timeout_seconds=timeout_seconds,
            batch_size=batch_size,
            max_input_candidates=max_input_candidates,
            max_candidate_chars=max_candidate_chars,
        )

    async def rerank(
        self,
        *,
        query: str,
        candidates: list[RerankCandidate],
        enabled: bool,
        final_top_k: int,
        settings_override: RerankSettings | None = None,
    ) -> RerankResult:
        if final_top_k < 1:
            raise ValueError("final_top_k must be at least 1")
        if not candidates:
            diagnostics = self._build_diagnostics(
                enabled=enabled,
                provider_key=None,
                model_name=None,
                requested_count=0,
                reranked_count=0,
                selected_count=0,
                batch_count=0,
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                fallback_used=False,
                fallback_reason=None,
                timeout_seconds=None,
                batch_size=self.default_batch_size,
                max_input_candidates=self.default_input_candidates,
                max_candidate_chars=self.default_candidate_chars,
            )
            return RerankResult(candidates=[], diagnostics=diagnostics)

        config = settings_override or RerankSettings(
            enabled=enabled,
            provider_key=self.default_provider_key,
            model_name=self.default_model_name,
            timeout_seconds=self.default_timeout_seconds,
            batch_size=self.default_batch_size,
            max_input_candidates=self.default_input_candidates,
            max_candidate_chars=self.default_candidate_chars,
            fallback_behavior=self.default_fallback_behavior,
        )

        input_limit = max(final_top_k, config.max_input_candidates or final_top_k)
        batch_size = max(1, min(config.batch_size or input_limit, input_limit))
        max_candidate_chars = max(128, config.max_candidate_chars or self.default_candidate_chars)
        timeout_seconds = config.timeout_seconds

        ordered_candidates = self._sorted_original(candidates)[:input_limit]
        if not config.enabled or not enabled:
            diagnostics = self._build_diagnostics(
                enabled=False,
                provider_key=config.provider_key,
                model_name=config.model_name,
                requested_count=len(candidates),
                reranked_count=len(ordered_candidates),
                selected_count=min(final_top_k, len(ordered_candidates)),
                batch_count=0,
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                fallback_used=False,
                fallback_reason=None,
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
                max_input_candidates=input_limit,
                max_candidate_chars=max_candidate_chars,
            )
            return self._build_fallback_result(
                candidates=ordered_candidates,
                final_top_k=final_top_k,
                diagnostics=diagnostics,
            )

        provider_factory = self._resolve_provider_factory()
        provider_key = (config.provider_key or self.default_provider_key or "").strip() or None
        model_name = (config.model_name or self.default_model_name or "").strip() or None

        if provider_key is None:
            fallback_diagnostics = self._build_diagnostics(
                enabled=True,
                provider_key=None,
                model_name=model_name,
                requested_count=len(candidates),
                reranked_count=len(ordered_candidates),
                selected_count=min(final_top_k, len(ordered_candidates)),
                batch_count=0,
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                fallback_used=True,
                fallback_reason="provider_not_configured",
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
                max_input_candidates=input_limit,
                max_candidate_chars=max_candidate_chars,
            )
            return self._build_fallback_result(
                candidates=ordered_candidates,
                final_top_k=final_top_k,
                diagnostics=fallback_diagnostics,
            )

        try:
            provider = provider_factory.get_chat_provider(provider_key)
        except Exception as exc:
            logger.warning(
                "rerank.provider_unavailable provider_key=%s error=%s",
                provider_key,
                exc.__class__.__name__,
            )
            diagnostics = self._build_diagnostics(
                enabled=True,
                provider_key=provider_key,
                model_name=model_name,
                requested_count=len(candidates),
                reranked_count=len(ordered_candidates),
                selected_count=min(final_top_k, len(ordered_candidates)),
                batch_count=0,
                latency_ms=0,
                prompt_tokens=0,
                completion_tokens=0,
                fallback_used=True,
                fallback_reason="provider_unavailable",
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
                max_input_candidates=input_limit,
                max_candidate_chars=max_candidate_chars,
            )
            return self._build_fallback_result(
                candidates=ordered_candidates,
                final_top_k=final_top_k,
                diagnostics=diagnostics,
            )

        start = perf_counter()
        all_scores: dict[str, float] = {}
        prompt_tokens = 0
        completion_tokens = 0
        batch_count = 0

        try:
            batches = [
                ordered_candidates[index : index + batch_size]
                for index in range(0, len(ordered_candidates), batch_size)
            ]
            for batch in batches:
                batch_count += 1
                batch_scores, batch_prompt_tokens, batch_completion_tokens, _ = await self._score_batch(
                    query=query,
                    batch=batch,
                    provider=provider,
                    model_name=model_name or self.default_model_name or settings.openai_llm_model,
                    timeout_seconds=timeout_seconds,
                    max_candidate_chars=max_candidate_chars,
                )
                prompt_tokens += batch_prompt_tokens
                completion_tokens += batch_completion_tokens
                for candidate, batch_score in zip(batch, batch_scores, strict=True):
                    all_scores[candidate.key] = self._clamp_score(batch_score.score)
        except TimeoutError as exc:
            logger.warning(
                "rerank.timeout provider_key=%s model=%s error=%s",
                provider_key,
                model_name,
                exc.__class__.__name__,
            )
            diagnostics = self._build_diagnostics(
                enabled=True,
                provider_key=provider_key,
                model_name=model_name,
                requested_count=len(candidates),
                reranked_count=len(ordered_candidates),
                selected_count=min(final_top_k, len(ordered_candidates)),
                batch_count=batch_count,
                latency_ms=int((perf_counter() - start) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                fallback_used=True,
                fallback_reason="timeout",
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
                max_input_candidates=input_limit,
                max_candidate_chars=max_candidate_chars,
            )
            return self._build_fallback_result(
                candidates=ordered_candidates,
                final_top_k=final_top_k,
                diagnostics=diagnostics,
            )
        except (UnsupportedCapabilityError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            logger.warning(
                "rerank.failed provider_key=%s model=%s error=%s",
                provider_key,
                model_name,
                exc.__class__.__name__,
            )
            diagnostics = self._build_diagnostics(
                enabled=True,
                provider_key=provider_key,
                model_name=model_name,
                requested_count=len(candidates),
                reranked_count=len(ordered_candidates),
                selected_count=min(final_top_k, len(ordered_candidates)),
                batch_count=batch_count,
                latency_ms=int((perf_counter() - start) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                fallback_used=True,
                fallback_reason=exc.__class__.__name__,
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
                max_input_candidates=input_limit,
                max_candidate_chars=max_candidate_chars,
            )
            return self._build_fallback_result(
                candidates=ordered_candidates,
                final_top_k=final_top_k,
                diagnostics=diagnostics,
            )
        except _TRANSIENT_PROVIDER_ERRORS as exc:
            logger.warning(
                "rerank.transient_failure provider_key=%s model=%s error=%s",
                provider_key,
                model_name,
                exc.__class__.__name__,
            )
            diagnostics = self._build_diagnostics(
                enabled=True,
                provider_key=provider_key,
                model_name=model_name,
                requested_count=len(candidates),
                reranked_count=len(ordered_candidates),
                selected_count=min(final_top_k, len(ordered_candidates)),
                batch_count=batch_count,
                latency_ms=int((perf_counter() - start) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                fallback_used=True,
                fallback_reason=exc.__class__.__name__,
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
                max_input_candidates=input_limit,
                max_candidate_chars=max_candidate_chars,
            )
            return self._build_fallback_result(
                candidates=ordered_candidates,
                final_top_k=final_top_k,
                diagnostics=diagnostics,
            )
        except Exception as exc:
            logger.warning(
                "rerank.unhandled_failure provider_key=%s model=%s error=%s",
                provider_key,
                model_name,
                exc.__class__.__name__,
            )
            diagnostics = self._build_diagnostics(
                enabled=True,
                provider_key=provider_key,
                model_name=model_name,
                requested_count=len(candidates),
                reranked_count=len(ordered_candidates),
                selected_count=min(final_top_k, len(ordered_candidates)),
                batch_count=batch_count,
                latency_ms=int((perf_counter() - start) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                fallback_used=True,
                fallback_reason=exc.__class__.__name__,
                timeout_seconds=timeout_seconds,
                batch_size=batch_size,
                max_input_candidates=input_limit,
                max_candidate_chars=max_candidate_chars,
            )
            return self._build_fallback_result(
                candidates=ordered_candidates,
                final_top_k=final_top_k,
                diagnostics=diagnostics,
            )

        reranked = [
            RerankedCandidate(
                key=candidate.key,
                similarity_score=self._clamp_score(candidate.similarity_score),
                original_rank=candidate.original_rank or index,
                rerank_score=all_scores[candidate.key],
                rerank_rank=index,
                final_rank=index,
            )
            for index, candidate in enumerate(
                sorted(
                    ordered_candidates,
                    key=lambda candidate: (
                        -all_scores.get(candidate.key, 0.0),
                        -(candidate.similarity_score),
                        candidate.original_rank or 0,
                        candidate.key,
                    ),
                )[:final_top_k],
                start=1,
            )
        ]
        diagnostics = self._build_diagnostics(
            enabled=True,
            provider_key=provider_key,
            model_name=model_name,
            requested_count=len(candidates),
            reranked_count=len(ordered_candidates),
            selected_count=len(reranked),
            batch_count=batch_count,
            latency_ms=int((perf_counter() - start) * 1000),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            fallback_used=False,
            fallback_reason=None,
            timeout_seconds=timeout_seconds,
            batch_size=batch_size,
            max_input_candidates=input_limit,
            max_candidate_chars=max_candidate_chars,
        )
        return RerankResult(candidates=reranked, diagnostics=diagnostics)
