"""Source freshness and trust-status scoring for RAG retrieval (F297/F311).

Documents are classified with a trust_status that describes their lifecycle:
  verified  → peer-reviewed/approved; gets a retrieval boost
  current   → default; neutral weight
  draft     → work-in-progress; small penalty
  stale     → past review_date or stale_after_days; medium penalty
  deprecated → superseded by policy; excluded by default
  superseded → replaced by a newer version; excluded by default
  expired    → past effective lifetime; excluded by default

F311 adds:
  - derive_freshness_state(): maps effective status to a normalized display enum
    (current / stale / expired / deprecated / draft / unreviewed / unknown)
  - Exclusion fallback: when all chunks are excluded, re-include them with a
    warning rather than returning an empty context window
  - preferred_source_bump(): micro-boost for tie-breaking toward trusted sources

The service is stateless and pure — it takes a list of retrieved chunks and
a pre-built trust map (indexed by document_id string) and returns adjusted
candidates.  The caller is responsible for fetching the trust map from the DB.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol, cast
from uuid import UUID

# Normalized single-value state for UI display (F311).
FreshnessState = Literal[
    "current",
    "stale",
    "expired",
    "deprecated",
    "draft",
    "unreviewed",
    "unknown",
]

# Micro-boost added on top of the trust-score multiplier to break ties in
# favour of preferred sources when two chunks score identically after the
# multiplier is applied.  Kept small enough (< 1 % of score) that it never
# overrides a genuine relevance difference.
PREFERRED_SOURCE_BUMP: float = 0.005

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRUST_SCORE_MULTIPLIERS: dict[str, float] = {
    "verified": 1.15,
    "reviewed": 1.07,
    "current": 1.0,
    "trusted": 1.1,
    "draft": 0.85,
    "unreviewed": 0.82,
    "stale": 0.7,
    "needs_review": 0.8,
    "archived": 0.2,
    "deprecated": 0.3,
    "superseded": 0.3,
    "expired": 0.3,
}

# Statuses excluded from retrieval by default when exclusion flags are enabled.
EXCLUDED_BY_DEFAULT: frozenset[str] = frozenset({"archived", "deprecated", "superseded"})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentTrustData:
    document_id: UUID
    trust_status: str
    quality_state: str | None = None
    review_status: str | None = None
    review_owner_id: UUID | None = None
    review_due_date: date | None = None
    expiry_date: date | None = None
    version_label: str | None = None
    review_date: date | None = None
    effective_date: date | None = None
    stale_after_days: int | None = None
    superseded_by_document_id: UUID | None = None
    trust_level: str | None = None
    last_updated_at: datetime | None = None


@dataclass(frozen=True)
class FreshnessFilterResult:
    excluded_document_ids: frozenset[str]
    excluded_count: int
    stale_document_ids: frozenset[str]


class _DocumentTrustSource(Protocol):
    id: UUID
    trust_status: str | None
    quality_state: str | None
    review_status: str | None
    review_owner_id: UUID | None
    review_due_date: date | None
    expiry_date: date | None
    version_label: str | None
    review_date: date | None
    effective_date: date | None
    stale_after_days: int | None
    superseded_by_document_id: UUID | None
    trust_level: str | None
    updated_at: datetime | None


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
            if doc.id is None:
                continue
            doc_id = str(doc.id)
            if not doc_id or doc_id == "None":
                continue
            trust_map[doc_id] = DocumentTrustData(
                document_id=cast(UUID, doc.id),
                trust_status=doc.trust_status or "current",
                quality_state=getattr(doc, "quality_state", None),
                review_status=doc.review_status or None,
                review_owner_id=doc.review_owner_id,
                review_due_date=doc.review_due_date,
                expiry_date=doc.expiry_date,
                version_label=doc.version_label,
                review_date=doc.review_date,
                effective_date=doc.effective_date,
                stale_after_days=doc.stale_after_days,
                superseded_by_document_id=doc.superseded_by_document_id,
                trust_level=doc.trust_level,
                last_updated_at=getattr(doc, "updated_at", None),
            )
        return trust_map

    def derive_freshness_state(
        self,
        trust_data: DocumentTrustData | None,
        *,
        today: date | None = None,
        org_stale_threshold_days: int | None = None,
    ) -> FreshnessState:
        """Map a document's trust data to a normalized UI freshness state (F311).

        The returned value is one of the FreshnessState literals:
          current   → trusted/verified/current with no staleness signals
          stale     → past review_date or stale_after_days threshold
          expired   → past expiry_date
          deprecated → archived, deprecated, or superseded
          draft     → work-in-progress with no review cycle started
          unreviewed → needs_review or long-pending without review
          unknown   → no trust metadata available
        """
        if trust_data is None:
            return "unknown"

        effective = self.compute_effective_trust_status(
            trust_data,
            today=today,
            org_stale_threshold_days=org_stale_threshold_days,
        )

        if effective in {"archived", "deprecated", "superseded"}:
            return "deprecated"
        if effective == "expired":
            return "expired"
        if effective == "stale":
            return "stale"
        if effective == "needs_review":
            return "unreviewed"
        if effective == "unreviewed":
            return "unreviewed"
        if effective == "draft":
            return "draft"
        if effective in {"reviewed", "verified", "current", "trusted"}:
            return "current"

        raw_status = (trust_data.trust_status or "current").lower()
        if raw_status == "draft":
            return "draft"
        if raw_status in {"verified", "trusted", "current", "reviewed"}:
            return "current"

        return "unknown"

    def derive_quality_state(
        self,
        trust_data: DocumentTrustData | None,
        *,
        today: date | None = None,
    ) -> str | None:
        """Return the explicit document quality workflow state for UI display."""
        if trust_data is None:
            return None

        explicit = (trust_data.quality_state or "").strip().lower()
        if explicit:
            return explicit

        effective = self.compute_effective_trust_status(trust_data, today=today)
        if effective == "draft":
            return "draft"
        if effective == "verified":
            return "verified"
        if effective in {"reviewed", "current", "trusted"}:
            return "reviewed"
        if effective == "needs_review":
            return "unreviewed"
        if effective == "stale":
            return "stale"
        if effective == "expired":
            return "expired"
        if effective in {"archived", "deprecated", "superseded"}:
            return "archived" if effective == "archived" else "deprecated"
        return "unreviewed"

    def compute_effective_trust_status(
        self,
        trust_data: DocumentTrustData,
        today: date | None = None,
        org_stale_threshold_days: int | None = None,
    ) -> str:
        """Return the effective trust status, promoting to 'stale' when past review_date."""
        status = (
            trust_data.quality_state
            or trust_data.review_status
            or trust_data.trust_status
            or "current"
        ).strip().lower()
        if status in {"reviewed", "verified", "trusted"}:
            return status
        if status in ("archived", "deprecated", "superseded", "expired", "stale"):
            return status
        if status == "draft":
            return status

        if status == "unreviewed":
            legacy_status = (
                trust_data.review_status or trust_data.trust_status or "current"
            ).strip().lower()
            if legacy_status in {"verified", "reviewed", "trusted", "current"}:
                return legacy_status
            if legacy_status in {"stale", "expired", "deprecated", "archived", "superseded"}:
                return legacy_status
            return status

        _today = today or date.today()

        if trust_data.expiry_date is not None and trust_data.expiry_date < _today:
            return "expired"

        if trust_data.review_due_date is not None and trust_data.review_due_date < _today:
            return "needs_review"

        # Past review_date → stale (regardless of current/verified/draft).
        if trust_data.review_date is not None and trust_data.review_date < _today:
            return "stale"

        if status == "unreviewed":
            return "unreviewed"
        return status

    def filter_excluded(
        self,
        chunk_document_ids: list[str],
        trust_map: dict[str, DocumentTrustData],
        *,
        exclude_deprecated: bool = True,
        exclude_expired: bool = True,
        today: date | None = None,
        org_stale_threshold_days: int | None = None,
    ) -> FreshnessFilterResult:
        """Return document IDs that should be excluded and those that are stale."""
        excluded: set[str] = set()
        stale: set[str] = set()
        excluded_statuses = set(EXCLUDED_BY_DEFAULT)
        if exclude_expired:
            excluded_statuses.add("expired")

        for doc_id in chunk_document_ids:
            trust = trust_map.get(doc_id)
            if trust is None:
                continue
            effective = self.compute_effective_trust_status(
                trust,
                today=today,
                org_stale_threshold_days=org_stale_threshold_days,
            )
            if effective == "expired" and not exclude_expired:
                stale.add(doc_id)
                continue
            if exclude_deprecated and effective in excluded_statuses:
                excluded.add(doc_id)
            elif effective in {"stale", "needs_review", "expired"}:
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
        """Adjust a retrieval score by the trust-status multiplier for a document.

        Also applies PREFERRED_SOURCE_BUMP (F311) for verified/trusted sources to
        break ties in favour of higher-trust content when relevance is comparable.
        """
        trust = trust_map.get(document_id)
        if trust is None:
            return score
        effective = self.compute_effective_trust_status(
            trust,
            today=today,
            org_stale_threshold_days=org_stale_threshold_days,
        )
        multiplier = TRUST_SCORE_MULTIPLIERS.get(effective, 1.0)
        adjusted = score * multiplier
        if effective in {"verified", "trusted"}:
            adjusted = min(1.0, adjusted + PREFERRED_SOURCE_BUMP)
        return adjusted

    def apply_exclusion_fallback(
        self,
        after_filter: list,
        before_filter: list,
        excluded_ids: frozenset[str],
    ) -> tuple[list, bool]:
        """Return a (chunks, fallback_used) pair for the exclusion-fallback rule (F311).

        When freshness filtering removes ALL chunks and leaves the context window
        empty, re-include the originally excluded chunks so the LLM can still
        attempt an answer.  A warning must be surfaced to the user in this case.

        Parameters
        ----------
        after_filter:  chunks remaining after exclusion (may be empty)
        before_filter: full pre-exclusion chunk list
        excluded_ids:  document_ids that were excluded

        Returns the effective chunk list and whether the fallback was triggered.
        """
        if after_filter or not excluded_ids or not before_filter:
            return after_filter, False
        return before_filter, True

    def build_warning_reasons(
        self,
        *,
        stale_count: int,
        excluded_count: int,
        unreviewed_count: int,
        deprecated_count: int,
        draft_count: int,
        all_excluded_fallback: bool,
    ) -> list[str]:
        """Build a structured list of specific freshness warning messages (F311)."""
        reasons: list[str] = []
        if all_excluded_fallback:
            reasons.append(
                "All preferred sources were excluded; answer uses deprecated or expired content."
            )
        if stale_count:
            reasons.append(
                f"{stale_count} cited source{'s' if stale_count > 1 else ''} "
                "may be outdated — content has not been reviewed recently."
            )
        if unreviewed_count:
            reasons.append(
                f"{unreviewed_count} source{'s' if unreviewed_count > 1 else ''} "
                "pending review — accuracy is not yet confirmed."
            )
        if draft_count:
            reasons.append(
                f"{draft_count} draft source{'s' if draft_count > 1 else ''} "
                "were cited before review completed."
            )
        if deprecated_count and not all_excluded_fallback:
            reasons.append(
                f"{deprecated_count} deprecated or archived source{'s were' if deprecated_count > 1 else ' was'} "
                "used because no current alternative was available."
            )
        if excluded_count and not all_excluded_fallback:
            reasons.append(
                f"{excluded_count} source{'s' if excluded_count > 1 else ''} "
                "excluded from retrieval due to deprecated or expired status."
            )
        return reasons
