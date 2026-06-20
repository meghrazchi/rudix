"""Source freshness and trust-status scoring for RAG retrieval (F297).

Documents are classified with a trust_status that describes their lifecycle:
  verified  → peer-reviewed/approved; gets a retrieval boost
  current   → default; neutral weight
  draft     → work-in-progress; small penalty
  stale     → past review_date or stale_after_days; medium penalty
  deprecated → superseded by policy; excluded by default
  superseded → replaced by a newer version; excluded by default
  expired    → past effective lifetime; excluded by default

The service is stateless and pure — it takes a list of retrieved chunks and
a pre-built trust map (indexed by document_id string) and returns adjusted
candidates.  The caller is responsible for fetching the trust map from the DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections.abc import Sequence
from typing import Protocol, cast
from uuid import UUID

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRUST_SCORE_MULTIPLIERS: dict[str, float] = {
    "verified": 1.15,
    "current": 1.0,
    "draft": 0.85,
    "stale": 0.7,
    "deprecated": 0.3,
    "superseded": 0.3,
    "expired": 0.3,
}

# Statuses excluded from retrieval by default when exclude_deprecated_docs=True.
EXCLUDED_BY_DEFAULT: frozenset[str] = frozenset({"deprecated", "superseded", "expired"})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentTrustData:
    document_id: UUID
    trust_status: str
    version_label: str | None = None
    review_date: date | None = None
    effective_date: date | None = None
    stale_after_days: int | None = None
    superseded_by_document_id: UUID | None = None


@dataclass(frozen=True)
class FreshnessFilterResult:
    excluded_document_ids: frozenset[str]
    excluded_count: int
    stale_document_ids: frozenset[str]


class _DocumentTrustSource(Protocol):
    id: UUID
    trust_status: str | None
    version_label: str | None
    review_date: date | None
    effective_date: date | None
    stale_after_days: int | None
    superseded_by_document_id: UUID | None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SourceFreshnessService:
    """Applies trust-status filtering and score boosting to retrieved candidates.

    All methods are synchronous and side-effect free.
    """

    def build_trust_map(
        self, documents: Sequence[_DocumentTrustSource]
    ) -> dict[str, DocumentTrustData]:
        """Build a document_id → DocumentTrustData index from ORM Document objects."""
        trust_map: dict[str, DocumentTrustData] = {}
        for doc in documents:
            doc_id = str(doc.id)
            if not doc_id:
                continue
            trust_map[doc_id] = DocumentTrustData(
                document_id=cast(UUID, doc.id),
                trust_status=doc.trust_status or "current",
                version_label=doc.version_label,
                review_date=doc.review_date,
                effective_date=doc.effective_date,
                stale_after_days=doc.stale_after_days,
                superseded_by_document_id=doc.superseded_by_document_id,
            )
        return trust_map

    def compute_effective_trust_status(
        self,
        trust_data: DocumentTrustData,
        today: date | None = None,
        org_stale_threshold_days: int | None = None,
    ) -> str:
        """Return the effective trust status, promoting to 'stale' when past review_date."""
        status = trust_data.trust_status
        if status in ("deprecated", "superseded", "expired", "stale"):
            return status

        _today = today or date.today()

        # Past review_date → stale (regardless of current/verified/draft).
        if trust_data.review_date is not None and trust_data.review_date < _today:
            return "stale"

        return status

    def filter_excluded(
        self,
        chunk_document_ids: list[str],
        trust_map: dict[str, DocumentTrustData],
        *,
        exclude_deprecated: bool = True,
        today: date | None = None,
        org_stale_threshold_days: int | None = None,
    ) -> FreshnessFilterResult:
        """Return document IDs that should be excluded and those that are stale."""
        excluded: set[str] = set()
        stale: set[str] = set()

        for doc_id in chunk_document_ids:
            trust = trust_map.get(doc_id)
            if trust is None:
                continue
            effective = self.compute_effective_trust_status(
                trust,
                today=today,
                org_stale_threshold_days=org_stale_threshold_days,
            )
            if exclude_deprecated and effective in EXCLUDED_BY_DEFAULT:
                excluded.add(doc_id)
            elif effective == "stale":
                stale.add(doc_id)

        return FreshnessFilterResult(
            excluded_document_ids=frozenset(excluded),
            excluded_count=len(excluded),
            stale_document_ids=frozenset(stale),
        )

    def apply_trust_score_multiplier(
        self,
        score: float,
        document_id: str,
        trust_map: dict[str, DocumentTrustData],
        *,
        today: date | None = None,
        org_stale_threshold_days: int | None = None,
    ) -> float:
        """Adjust a retrieval score by the trust-status multiplier for a document."""
        trust = trust_map.get(document_id)
        if trust is None:
            return score
        effective = self.compute_effective_trust_status(
            trust,
            today=today,
            org_stale_threshold_days=org_stale_threshold_days,
        )
        multiplier = TRUST_SCORE_MULTIPLIERS.get(effective, 1.0)
        return score * multiplier
