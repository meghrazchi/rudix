from __future__ import annotations

import re
from dataclasses import dataclass
from math import sqrt

from app.core.config import settings

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class RerankCandidate:
    key: str
    text: str
    similarity_score: float


@dataclass(frozen=True)
class RerankedCandidate:
    key: str
    similarity_score: float
    rerank_score: float | None
    rerank_rank: int | None


class RerankService:
    """MMR reranking service for balancing relevance and diversity."""

    def __init__(
        self,
        *,
        mmr_lambda: float | None = None,
        candidate_count: int | None = None,
        duplicate_similarity_threshold: float | None = None,
    ) -> None:
        self.mmr_lambda = settings.rerank_mmr_lambda if mmr_lambda is None else mmr_lambda
        self.candidate_count = (
            settings.rerank_mmr_candidate_count if candidate_count is None else candidate_count
        )
        self.duplicate_similarity_threshold = (
            settings.rerank_mmr_duplicate_similarity_threshold
            if duplicate_similarity_threshold is None
            else duplicate_similarity_threshold
        )

    @staticmethod
    def _tokenize(text: str) -> dict[str, int]:
        term_counts: dict[str, int] = {}
        for token in _TOKEN_PATTERN.findall(text.lower()):
            term_counts[token] = term_counts.get(token, 0) + 1
        return term_counts

    @staticmethod
    def _cosine_similarity(a: dict[str, int], b: dict[str, int]) -> float:
        if not a or not b:
            return 0.0

        common = set(a.keys()).intersection(b.keys())
        dot_product = sum(a[token] * b[token] for token in common)
        if dot_product == 0:
            return 0.0

        a_norm = sqrt(sum(value * value for value in a.values()))
        b_norm = sqrt(sum(value * value for value in b.values()))
        if a_norm == 0 or b_norm == 0:
            return 0.0
        return dot_product / (a_norm * b_norm)

    @staticmethod
    def _clamp_score(value: float) -> float:
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return value

    def rerank(
        self,
        *,
        candidates: list[RerankCandidate],
        enabled: bool,
        final_top_k: int,
    ) -> list[RerankedCandidate]:
        if final_top_k < 1:
            raise ValueError("final_top_k must be at least 1")
        if self.candidate_count < 1:
            raise ValueError("candidate_count must be at least 1")

        if not candidates:
            return []

        ranked_by_similarity = sorted(
            candidates,
            key=lambda candidate: (candidate.similarity_score, candidate.key),
            reverse=True,
        )
        pool_size = min(len(ranked_by_similarity), max(final_top_k, self.candidate_count))
        pool = ranked_by_similarity[:pool_size]

        if not enabled:
            return [
                RerankedCandidate(
                    key=candidate.key,
                    similarity_score=candidate.similarity_score,
                    rerank_score=None,
                    rerank_rank=None,
                )
                for candidate in pool[:final_top_k]
            ]

        token_cache = {candidate.key: self._tokenize(candidate.text) for candidate in pool}
        selected: list[tuple[RerankCandidate, float]] = []
        remaining = list(pool)

        while remaining and len(selected) < final_top_k:
            if not selected:
                chosen = remaining.pop(0)
                selected.append((chosen, self._clamp_score(chosen.similarity_score)))
                continue

            scored: list[tuple[RerankCandidate, float, float]] = []
            for candidate in remaining:
                candidate_tokens = token_cache[candidate.key]
                max_similarity_to_selected = max(
                    self._cosine_similarity(candidate_tokens, token_cache[chosen.key])
                    for chosen, _ in selected
                )
                relevance = self._clamp_score(candidate.similarity_score)
                mmr_score = (self.mmr_lambda * relevance) - (
                    (1.0 - self.mmr_lambda) * max_similarity_to_selected
                )
                scored.append((candidate, mmr_score, max_similarity_to_selected))

            non_duplicates = [
                item for item in scored if item[2] < self.duplicate_similarity_threshold
            ]
            pick_from = non_duplicates if non_duplicates else scored
            pick_from.sort(
                key=lambda item: (
                    item[1],
                    item[0].similarity_score,
                    item[0].key,
                ),
                reverse=True,
            )
            chosen_candidate, chosen_score, _ = pick_from[0]
            selected.append((chosen_candidate, chosen_score))
            remaining = [
                candidate for candidate in remaining if candidate.key != chosen_candidate.key
            ]

        return [
            RerankedCandidate(
                key=candidate.key,
                similarity_score=candidate.similarity_score,
                rerank_score=score,
                rerank_rank=index,
            )
            for index, (candidate, score) in enumerate(selected, start=1)
        ]
