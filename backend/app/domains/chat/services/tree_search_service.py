from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean
from time import perf_counter
from typing import Any, Literal

from app.core.config import settings
from app.domains.chat.schemas.chat import ChatCitationResponse
from app.domains.chat.services.citation_service import CitationContextChunk, CitationService
from app.domains.chat.services.confidence_service import ConfidenceChunkSignal, ConfidenceService
from app.domains.chat.services.llm_service import LLMAnswerResult, LLMService
from app.domains.chat.services.prompt_service import PromptContextChunk, PromptService

TreeSearchStrategy = Literal[
    "conservative",
    "balanced",
    "alternative_interpretation",
]


@dataclass(frozen=True)
class TreeSearchStrategySpec:
    name: TreeSearchStrategy
    label: str
    risk_penalty: float
    instruction: str


@dataclass(frozen=True)
class TreeSearchCandidateDraft:
    strategy: TreeSearchStrategy
    strategy_label: str
    risk_penalty: float
    llm_result: LLMAnswerResult


@dataclass(frozen=True)
class TreeSearchGenerationResult:
    candidates: list[TreeSearchCandidateDraft]
    total_tokens: int
    total_cost_usd: Decimal
    latency_ms: int
    timeout_hit: bool = False
    cost_limit_hit: bool = False
    token_limit_hit: bool = False
    failed: bool = False

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)


@dataclass(frozen=True)
class TreeSearchScoringSignals:
    freshness_multiplier: float
    ocr_quality_multiplier: float
    conflict_multiplier: float
    table_quality_multiplier: float
    extraction_quality_multiplier: float
    graph_context_used: bool


@dataclass(frozen=True)
class TreeSearchCandidateScore:
    strategy: TreeSearchStrategy
    strategy_label: str
    score: float
    citation_support_score: float
    citation_validation_score: float
    citation_coverage_score: float
    source_trust_score: float
    freshness_score: float
    conflict_score: float
    completeness_score: float
    risk_penalty: float
    confidence_score: float
    confidence_category: str
    confidence_trust_level: str
    not_found: bool
    citation_count: int


@dataclass(frozen=True)
class TreeSearchSelectionResult:
    selected_candidate: TreeSearchCandidateScore | None
    accepted: bool
    selection_reason: str


_TREE_SEARCH_STRATEGIES: tuple[TreeSearchStrategySpec, ...] = (
    TreeSearchStrategySpec(
        name="conservative",
        label="Conservative",
        risk_penalty=0.0,
        instruction=(
            "Tree-search mode: prefer refusal unless the answer is directly supported and "
            "unambiguous. When sources conflict, state that clearly and avoid speculation."
        ),
    ),
    TreeSearchStrategySpec(
        name="balanced",
        label="Balanced",
        risk_penalty=0.05,
        instruction=(
            "Tree-search mode: synthesize the best supported answer across sources. If the "
            "evidence does not fully agree, acknowledge uncertainty and identify the strongest "
            "supported interpretation."
        ),
    ),
    TreeSearchStrategySpec(
        name="alternative_interpretation",
        label="Alternative interpretations",
        risk_penalty=0.10,
        instruction=(
            "Tree-search mode: when the sources support more than one plausible reading, "
            "present the interpretations side by side and say which sources support each one."
        ),
    ),
)

_TRUST_STATUS_SCORES: dict[str, float] = {
    "verified": 1.0,
    "trusted": 1.0,
    "current": 0.96,
    "uploaded": 0.86,
    "unknown": 0.62,
    "draft": 0.55,
    "stale": 0.40,
    "deprecated": 0.30,
    "superseded": 0.25,
    "expired": 0.18,
    "revoked": 0.10,
    "deleted": 0.0,
}

_FRESHNESS_STATE_SCORES: dict[str, float] = {
    "current": 1.0,
    "stale": 0.60,
    "expired": 0.20,
    "deprecated": 0.30,
    "draft": 0.45,
    "unreviewed": 0.58,
    "unknown": 0.65,
}


class TreeSearchService:
    def __init__(
        self,
        *,
        llm_service: LLMService | None = None,
        prompt_service: PromptService | None = None,
        citation_service: CitationService | None = None,
        confidence_service: ConfidenceService | None = None,
        strategy_specs: tuple[TreeSearchStrategySpec, ...] | None = None,
    ) -> None:
        self._llm_service = llm_service or LLMService()
        self._prompt_service = prompt_service or PromptService()
        self._citation_service = citation_service or CitationService()
        self._confidence_service = confidence_service or ConfidenceService()
        self._strategy_specs = strategy_specs or _TREE_SEARCH_STRATEGIES

    @staticmethod
    def _to_prompt_chunks(chunks: list[CitationContextChunk]) -> list[PromptContextChunk]:
        return [
            PromptContextChunk(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=chunk.original_rank,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
            )
            for chunk in chunks
        ]

    async def generate_candidates(
        self,
        *,
        question: str,
        context_chunks: list[CitationContextChunk],
        not_found_answer: str,
        conflict_context: str = "",
        answer_language: str | None = None,
        resolved_profile: Any | None = None,
        max_candidates: int | None = None,
        timeout_seconds: float | None = None,
        max_total_tokens: int | None = None,
        max_total_cost_usd: Decimal | None = None,
    ) -> TreeSearchGenerationResult:
        started = perf_counter()
        if not context_chunks:
            return TreeSearchGenerationResult(
                candidates=[],
                total_tokens=0,
                total_cost_usd=Decimal("0"),
                latency_ms=0,
                failed=True,
            )

        prompt_chunks = self._to_prompt_chunks(context_chunks)
        strategy_limit = max_candidates or settings.tree_search_max_candidates
        token_limit = max_total_tokens or settings.tree_search_max_total_tokens
        cost_limit = (
            max_total_cost_usd
            if max_total_cost_usd is not None
            else Decimal(str(settings.tree_search_max_total_cost_usd))
        )
        timeout_budget = (
            timeout_seconds if timeout_seconds is not None else settings.tree_search_timeout_seconds
        )
        effective_specs = list(self._strategy_specs[:strategy_limit])
        candidates: list[TreeSearchCandidateDraft] = []
        total_tokens = 0
        total_cost = Decimal("0")
        timeout_hit = False
        token_limit_hit = False
        cost_limit_hit = False
        overall_failed = False

        for index, spec in enumerate(effective_specs, start=1):
            if timeout_budget is not None:
                elapsed = perf_counter() - started
                remaining = timeout_budget - elapsed
                if remaining <= 0:
                    timeout_hit = True
                    break
            else:
                remaining = None

            prompt = self._prompt_service.build_prompt(
                question=question,
                chunks=prompt_chunks,
                not_found_answer=not_found_answer,
                conflict_context=conflict_context,
                strategy_instruction=f" {spec.instruction}",
                answer_language=answer_language,
            )
            try:
                if remaining is not None:
                    llm_result = await asyncio.wait_for(
                        self._llm_service.generate_answer(
                            prompt=prompt,
                            resolved_profile=resolved_profile,
                        ),
                        timeout=max(0.001, remaining),
                    )
                else:
                    llm_result = await self._llm_service.generate_answer(
                        prompt=prompt,
                        resolved_profile=resolved_profile,
                    )
            except TimeoutError:
                timeout_hit = True
                overall_failed = not candidates
                break
            except Exception:
                overall_failed = not candidates
                continue

            candidate = TreeSearchCandidateDraft(
                strategy=spec.name,
                strategy_label=spec.label,
                risk_penalty=spec.risk_penalty,
                llm_result=llm_result,
            )
            candidates.append(candidate)
            total_tokens += llm_result.total_tokens
            total_cost += llm_result.approximate_cost_usd

            if token_limit is not None and total_tokens >= token_limit:
                token_limit_hit = True
                break
            if cost_limit is not None and total_cost >= cost_limit:
                cost_limit_hit = True
                break
            if index >= strategy_limit:
                break

        latency_ms = int((perf_counter() - started) * 1000)
        if not candidates:
            overall_failed = True
        return TreeSearchGenerationResult(
            candidates=candidates,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            latency_ms=latency_ms,
            timeout_hit=timeout_hit,
            cost_limit_hit=cost_limit_hit,
            token_limit_hit=token_limit_hit,
            failed=overall_failed,
        )

    def score_candidate(
        self,
        *,
        candidate: TreeSearchCandidateDraft,
        citations: list[ChatCitationResponse],
        confidence_signals: list[ConfidenceChunkSignal],
        citation_validation_score: float,
        freshness_multiplier: float,
        ocr_quality_multiplier: float,
        conflict_multiplier: float,
        table_quality_multiplier: float,
        extraction_quality_multiplier: float,
        graph_context_used: bool,
    ) -> TreeSearchCandidateScore:
        confidence_result = self._confidence_service.score(
            chunks=confidence_signals,
            citation_count=len(citations),
            citation_validation_score=citation_validation_score,
            not_found_signal=candidate.llm_result.not_found,
            freshness_multiplier=freshness_multiplier,
            ocr_quality_multiplier=ocr_quality_multiplier,
            conflict_multiplier=conflict_multiplier,
            table_quality_multiplier=table_quality_multiplier,
            extraction_quality_multiplier=extraction_quality_multiplier,
            graph_context_used=graph_context_used,
        )
        support_score = confidence_result.explanation.citation_support_score
        coverage_score = confidence_result.explanation.citation_coverage_score
        trust_score = self._source_trust_score(citations)
        freshness_score = confidence_result.explanation.freshness_multiplier
        conflict_score = confidence_result.explanation.conflict_multiplier
        risk_score = max(0.0, 1.0 - candidate.risk_penalty)
        final_score = self._clamp(
            0.30 * support_score
            + 0.15 * confidence_result.explanation.citation_validation_score
            + 0.15 * coverage_score
            + 0.15 * trust_score
            + 0.10 * freshness_score
            + 0.10 * conflict_score
            + 0.05 * risk_score
        )
        if candidate.llm_result.not_found and not citations:
            final_score = self._clamp(final_score + 0.03)
        return TreeSearchCandidateScore(
            strategy=candidate.strategy,
            strategy_label=candidate.strategy_label,
            score=final_score,
            citation_support_score=support_score,
            citation_validation_score=confidence_result.explanation.citation_validation_score,
            citation_coverage_score=coverage_score,
            source_trust_score=trust_score,
            freshness_score=freshness_score,
            conflict_score=conflict_score,
            completeness_score=coverage_score,
            risk_penalty=candidate.risk_penalty,
            confidence_score=confidence_result.score,
            confidence_category=confidence_result.category,
            confidence_trust_level=confidence_result.trust_level,
            not_found=candidate.llm_result.not_found,
            citation_count=len(citations),
        )

    @staticmethod
    def select_candidate(
        candidates: list[TreeSearchCandidateScore],
        *,
        min_selected_score: float | None = None,
    ) -> TreeSearchSelectionResult:
        if not candidates:
            return TreeSearchSelectionResult(
                selected_candidate=None,
                accepted=False,
                selection_reason="no_candidates",
            )
        selected = max(
            candidates,
            key=lambda candidate: (
                candidate.score,
                1 if candidate.not_found else 0,
                candidate.citation_validation_score,
                candidate.citation_count,
                -candidate.risk_penalty,
            ),
        )
        threshold = (
            min_selected_score
            if min_selected_score is not None
            else settings.tree_search_min_selected_score
        )
        accepted = selected.score >= threshold
        return TreeSearchSelectionResult(
            selected_candidate=selected,
            accepted=accepted,
            selection_reason="accepted" if accepted else "below_threshold",
        )

    @staticmethod
    def _source_trust_score(citations: list[ChatCitationResponse]) -> float:
        if not citations:
            return 0.5
        values: list[float] = []
        for citation in citations:
            trust_status = (
                str(citation.doc_trust_status or citation.source_trust_status or "").strip().lower()
            )
            freshness_state = str(citation.freshness_state or "").strip().lower()
            score = _TRUST_STATUS_SCORES.get(trust_status, 0.6)
            freshness_score = _FRESHNESS_STATE_SCORES.get(freshness_state, 0.65)
            score = min(score, freshness_score) if freshness_state else score
            if citation.doc_stale_warning or citation.doc_expired_warning:
                score = min(score, 0.45)
            if citation.doc_deprecated_warning or citation.doc_draft_warning:
                score = min(score, 0.55)
            if citation.doc_unreviewed_warning:
                score = min(score, 0.60)
            if citation.doc_is_excluded_status:
                score = min(score, 0.30)
            values.append(score)
        return round(mean(values), 4)

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, value))
