"""Entity normalization, canonicalization, and merge/candidate scoring (F285).

This service keeps entity resolution logic separate from the Neo4j persistence
layer so that:
- canonicalization heuristics can be tested without a live graph
- entity-scoped safety rules stay explicit
- manual merge/split decisions can be recorded later without changing the
  ingestion path

The service is intentionally conservative:
- exact source IDs and exact normalized-name matches are treated as high
  confidence signals
- aliases contribute to candidate scoring, but do not force auto-merges by
  themselves unless the combined score crosses the configured threshold
- low-confidence candidates are returned for review instead of being merged
  automatically
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from app.core.config import settings

ResolutionStatus = Literal["auto_merged", "review", "new"]
DecisionKind = Literal["merge", "split"]

_ENTITY_NAMESPACE = uuid.UUID("8d9a0e7e-97cb-46ce-8ad0-0f2f7f4e5d00")
_ALIAS_NAMESPACE = uuid.UUID("5f2f7a57-6f75-4d46-a5a2-1abf1f1d1100")
_CANDIDATE_NAMESPACE = uuid.UUID("c5dfe61c-1af2-46fe-8dfb-3f05f1a88b00")
_DECISION_NAMESPACE = uuid.UUID("f3cf8a1a-c4c8-40f6-8cf6-8b0f3b3c8300")


def normalize_entity_name(value: str) -> str:
    """Return a safe canonical key for entity matching.

    The normalization is intentionally simple and deterministic: it removes
    diacritics, lowercases, strips punctuation, and collapses whitespace.
    """
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^\w\s]+", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_source_id(value: str) -> str:
    return normalize_entity_name(value)


def entity_resolution_key(
    *,
    organization_id: str,
    entity_type: str,
    canonical_name: str,
    source_external_id: str | None = None,
    source_connector: str | None = None,
    language: str | None = None,
) -> uuid.UUID:
    """Deterministically derive a canonical entity UUID."""
    parts = [organization_id, entity_type, normalize_entity_name(canonical_name)]
    if source_external_id:
        parts.append(f"external:{normalize_source_id(source_external_id)}")
    if source_connector:
        parts.append(f"connector:{normalize_source_id(source_connector)}")
    if language:
        parts.append(f"language:{normalize_source_id(language)}")
    return uuid.uuid5(_ENTITY_NAMESPACE, "::".join(parts))


def entity_alias_key(
    *,
    organization_id: str,
    entity_id: str,
    alias_name: str,
    source_document_id: str | None = None,
    chunk_id: str | None = None,
    source_external_id: str | None = None,
    source_connector: str | None = None,
    language: str | None = None,
) -> uuid.UUID:
    """Deterministically derive a source mention UUID for an alias record."""
    parts = [
        organization_id,
        entity_id,
        normalize_entity_name(alias_name),
        source_document_id or "",
        chunk_id or "",
        source_external_id or "",
        source_connector or "",
        language or "",
    ]
    return uuid.uuid5(_ALIAS_NAMESPACE, "::".join(parts))


def resolution_candidate_key(
    *,
    organization_id: str,
    entity_type: str,
    normalized_name: str,
    source_external_id: str | None = None,
) -> uuid.UUID:
    parts = [
        organization_id,
        entity_type,
        normalized_name,
        source_external_id or "",
    ]
    return uuid.uuid5(_CANDIDATE_NAMESPACE, "::".join(parts))


def resolution_decision_key(
    *,
    organization_id: str,
    decision_kind: DecisionKind,
    target_entity_id: str,
    source_entity_ids: list[str],
) -> uuid.UUID:
    parts = [organization_id, decision_kind, target_entity_id, *sorted(source_entity_ids)]
    return uuid.uuid5(_DECISION_NAMESPACE, "::".join(parts))


@dataclass(frozen=True)
class EntityResolutionInput:
    organization_id: str
    entity_type: str
    canonical_name: str
    original_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    source_external_id: str | None = None
    source_connector: str | None = None
    language: str | None = None
    embedding_similarity: float | None = None

    @property
    def normalized_name(self) -> str:
        return normalize_entity_name(self.canonical_name)

    @property
    def all_names(self) -> list[str]:
        names = [self.canonical_name]
        if self.original_name:
            names.append(self.original_name)
        names.extend(self.aliases)
        return [name for name in names if name.strip()]


@dataclass(frozen=True)
class EntityResolutionCandidate:
    entity_id: uuid.UUID
    canonical_name: str
    normalized_name: str
    entity_type: str
    score: float
    matched_on: list[str] = field(default_factory=list)
    alias_count: int = 0
    aliases: list[str] = field(default_factory=list)
    source_external_id: str | None = None
    resolution_status: str | None = None


@dataclass(frozen=True)
class EntityResolutionResult:
    status: ResolutionStatus
    canonical_entity_id: uuid.UUID
    canonical_name: str
    candidate_score: float
    matched_on: list[str]
    reviewed_candidate_id: uuid.UUID | None = None
    review_required: bool = False


@dataclass(frozen=True)
class EntityMergeDecision:
    decision_id: uuid.UUID
    target_entity_id: uuid.UUID
    source_entity_ids: list[uuid.UUID]
    reason: str | None = None
    reviewer_id: str | None = None


@dataclass(frozen=True)
class EntitySplitDecision:
    decision_id: uuid.UUID
    target_entity_id: uuid.UUID
    source_entity_ids: list[uuid.UUID]
    reason: str | None = None
    reviewer_id: str | None = None


def _sequence_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right).ratio()


def _score_candidate(
    *,
    input_: EntityResolutionInput,
    candidate: EntityResolutionCandidate,
) -> tuple[float, list[str]]:
    matched_on: list[str] = []
    score = 0.0

    if input_.source_external_id and candidate.source_external_id:
        if normalize_source_id(input_.source_external_id) == normalize_source_id(
            candidate.source_external_id
        ):
            matched_on.append("exact_source_id")
            score = max(score, 1.0)

    normalized_input = input_.normalized_name
    normalized_candidate = candidate.normalized_name
    candidate_alias_norms = {
        normalize_entity_name(candidate_alias) for candidate_alias in candidate.aliases
    }
    if normalized_input == normalized_candidate:
        matched_on.append("normalized_name")
        score = max(score, 0.98)
    else:
        name_similarity = _sequence_similarity(normalized_input, normalized_candidate)
        if name_similarity >= 0.9:
            matched_on.append("similar_name")
        score = max(score, name_similarity * 0.9)

    for alias in input_.aliases:
        alias_normalized = normalize_entity_name(alias)
        if alias_normalized == normalized_candidate:
            matched_on.append("alias_name")
            score = max(score, 0.96)
            break
        if alias_normalized in candidate_alias_norms:
            matched_on.append("alias_match")
            score = max(score, 0.95)
            break

    if input_.embedding_similarity is not None:
        similarity = max(0.0, min(input_.embedding_similarity, 1.0))
        score = max(score, 0.65 * score + 0.35 * similarity)
        if similarity >= 0.9:
            matched_on.append("embedding_similarity")

    if input_.source_connector and candidate.resolution_status == "manual_split":
        score = 0.0
        matched_on.append("split_blocked")

    return round(score, 4), matched_on


class EntityResolutionService:
    """Score and resolve entity candidates without leaking cross-tenant data."""

    def __init__(
        self,
        *,
        auto_merge_threshold: float | None = None,
        review_threshold: float | None = None,
    ) -> None:
        self._auto_merge_threshold = (
            settings.entity_resolution_auto_merge_threshold
            if auto_merge_threshold is None
            else auto_merge_threshold
        )
        self._review_threshold = (
            settings.entity_resolution_review_threshold
            if review_threshold is None
            else review_threshold
        )

    @property
    def auto_merge_threshold(self) -> float:
        return self._auto_merge_threshold

    @property
    def review_threshold(self) -> float:
        return self._review_threshold

    def build_entity_id(self, input_: EntityResolutionInput) -> uuid.UUID:
        return entity_resolution_key(
            organization_id=input_.organization_id,
            entity_type=input_.entity_type,
            canonical_name=input_.canonical_name,
            source_external_id=input_.source_external_id,
            source_connector=input_.source_connector,
            language=input_.language,
        )

    def build_alias_id(
        self,
        *,
        input_: EntityResolutionInput,
        entity_id: uuid.UUID,
        alias_name: str,
        source_document_id: str | None = None,
        chunk_id: str | None = None,
    ) -> uuid.UUID:
        return entity_alias_key(
            organization_id=input_.organization_id,
            entity_id=str(entity_id),
            alias_name=alias_name,
            source_document_id=source_document_id,
            chunk_id=chunk_id,
            source_external_id=input_.source_external_id,
            source_connector=input_.source_connector,
            language=input_.language,
        )

    def build_candidate_id(
        self,
        *,
        input_: EntityResolutionInput,
    ) -> uuid.UUID:
        return resolution_candidate_key(
            organization_id=input_.organization_id,
            entity_type=input_.entity_type,
            normalized_name=input_.normalized_name,
            source_external_id=input_.source_external_id,
        )

    def build_merge_decision_id(
        self,
        *,
        organization_id: str,
        target_entity_id: str,
        source_entity_ids: list[str],
    ) -> uuid.UUID:
        return resolution_decision_key(
            organization_id=organization_id,
            decision_kind="merge",
            target_entity_id=target_entity_id,
            source_entity_ids=source_entity_ids,
        )

    def build_split_decision_id(
        self,
        *,
        organization_id: str,
        target_entity_id: str,
        source_entity_ids: list[str],
    ) -> uuid.UUID:
        return resolution_decision_key(
            organization_id=organization_id,
            decision_kind="split",
            target_entity_id=target_entity_id,
            source_entity_ids=source_entity_ids,
        )

    def score_candidates(
        self,
        *,
        input_: EntityResolutionInput,
        candidates: list[EntityResolutionCandidate],
    ) -> list[EntityResolutionCandidate]:
        scored: list[EntityResolutionCandidate] = []
        for candidate in candidates:
            score, matched_on = _score_candidate(input_=input_, candidate=candidate)
            scored.append(
                EntityResolutionCandidate(
                    entity_id=candidate.entity_id,
                    canonical_name=candidate.canonical_name,
                    normalized_name=candidate.normalized_name,
                    entity_type=candidate.entity_type,
                    score=score,
                    matched_on=matched_on,
                    alias_count=candidate.alias_count,
                    source_external_id=candidate.source_external_id,
                    resolution_status=candidate.resolution_status,
                )
            )
        scored.sort(
            key=lambda item: (item.score, item.alias_count, item.canonical_name), reverse=True
        )
        return scored

    async def resolve_entity(
        self,
        *,
        repository: object,
        input_: EntityResolutionInput,
    ) -> EntityResolutionResult:
        """Resolve an entity against existing canonical records.

        The repository must provide ``find_entity_resolution_candidates``.
        """
        find_candidates = getattr(repository, "find_entity_resolution_candidates", None)
        if find_candidates is None:
            raise TypeError("repository must provide find_entity_resolution_candidates()")

        candidates_raw = await find_candidates(
            organization_id=input_.organization_id,
            entity_type=input_.entity_type,
            normalized_name=input_.normalized_name,
            aliases=[normalize_entity_name(alias) for alias in input_.aliases],
            source_external_id=input_.source_external_id,
            limit=10,
        )
        candidates = [
            EntityResolutionCandidate(
                entity_id=uuid.UUID(candidate["entity_id"]),
                canonical_name=candidate["canonical_name"],
                normalized_name=candidate["normalized_name"],
                entity_type=candidate["entity_type"],
                score=float(candidate.get("score") or 0.0),
                matched_on=list(candidate.get("matched_on") or []),
                alias_count=int(candidate.get("alias_count") or 0),
                aliases=list(candidate.get("aliases") or []),
                source_external_id=candidate.get("source_external_id"),
                resolution_status=candidate.get("resolution_status"),
            )
            for candidate in candidates_raw
        ]
        scored = self.score_candidates(input_=input_, candidates=candidates)
        best = scored[0] if scored else None

        if best is None:
            return EntityResolutionResult(
                status="new",
                canonical_entity_id=self.build_entity_id(input_),
                canonical_name=input_.canonical_name,
                candidate_score=0.0,
                matched_on=[],
                review_required=False,
            )

        if best.score >= self._auto_merge_threshold:
            return EntityResolutionResult(
                status="auto_merged",
                canonical_entity_id=best.entity_id,
                canonical_name=best.canonical_name,
                candidate_score=best.score,
                matched_on=best.matched_on,
                reviewed_candidate_id=best.entity_id,
                review_required=False,
            )

        if best.score >= self._review_threshold:
            return EntityResolutionResult(
                status="review",
                canonical_entity_id=self.build_entity_id(input_),
                canonical_name=input_.canonical_name,
                candidate_score=best.score,
                matched_on=best.matched_on,
                reviewed_candidate_id=best.entity_id,
                review_required=True,
            )

        return EntityResolutionResult(
            status="new",
            canonical_entity_id=self.build_entity_id(input_),
            canonical_name=input_.canonical_name,
            candidate_score=best.score,
            matched_on=best.matched_on,
            reviewed_candidate_id=best.entity_id,
            review_required=False,
        )

    async def record_merge_decision(
        self,
        *,
        repository: object,
        organization_id: str,
        target_entity_id: str,
        source_entity_ids: list[str],
        reason: str | None = None,
        reviewer_id: str | None = None,
    ) -> EntityMergeDecision:
        record = EntityMergeDecision(
            decision_id=self.build_merge_decision_id(
                organization_id=organization_id,
                target_entity_id=target_entity_id,
                source_entity_ids=source_entity_ids,
            ),
            target_entity_id=uuid.UUID(str(target_entity_id)),
            source_entity_ids=[uuid.UUID(str(entity_id)) for entity_id in source_entity_ids],
            reason=reason,
            reviewer_id=reviewer_id,
        )
        recorder = getattr(repository, "record_entity_merge_decision", None)
        if recorder is None:
            raise TypeError("repository must provide record_entity_merge_decision()")
        await recorder(
            organization_id=organization_id,
            decision_id=record.decision_id,
            target_entity_id=target_entity_id,
            source_entity_ids=source_entity_ids,
            reason=reason,
            reviewer_id=reviewer_id,
        )
        return record

    async def record_split_decision(
        self,
        *,
        repository: object,
        organization_id: str,
        target_entity_id: str,
        source_entity_ids: list[str],
        reason: str | None = None,
        reviewer_id: str | None = None,
    ) -> EntitySplitDecision:
        record = EntitySplitDecision(
            decision_id=self.build_split_decision_id(
                organization_id=organization_id,
                target_entity_id=target_entity_id,
                source_entity_ids=source_entity_ids,
            ),
            target_entity_id=uuid.UUID(str(target_entity_id)),
            source_entity_ids=[uuid.UUID(str(entity_id)) for entity_id in source_entity_ids],
            reason=reason,
            reviewer_id=reviewer_id,
        )
        recorder = getattr(repository, "record_entity_split_decision", None)
        if recorder is None:
            raise TypeError("repository must provide record_entity_split_decision()")
        await recorder(
            organization_id=organization_id,
            decision_id=record.decision_id,
            target_entity_id=target_entity_id,
            source_entity_ids=source_entity_ids,
            reason=reason,
            reviewer_id=reviewer_id,
        )
        return record
