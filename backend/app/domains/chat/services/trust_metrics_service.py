"""Trust panel observability — emit UsageEvent rows for trust metrics (F317).

Called after each chat answer is generated. Stores trust score distributions,
warning signals, citation support, and not-found behaviour in the existing
usage_events table so the admin trust-analytics endpoint can aggregate them.

Privacy rules:
  - No raw question/answer text is stored.
  - Document IDs and chunk IDs are not stored.
  - Langfuse trace IDs are stored only when Langfuse is enabled.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.admin.repositories.usage import UsageRepository

_logger = logging.getLogger("observability.trust_metrics")

_TRUST_EVENT_TYPE = "trust.answer_metrics"


@dataclass(frozen=True)
class TrustMetricsSnapshot:
    """Flat snapshot of trust signals for a single answered turn."""

    # Identity
    organization_id: UUID
    user_id: UUID | None
    message_id: str
    session_id: str
    # Trust scores
    trust_level: str | None  # high / medium / low / warning / not_found
    confidence_score: float | None
    confidence_category: str | None  # high / medium / low
    citation_support_score: float | None
    verification_support_score: float | None
    # Signals
    not_found: bool
    citation_validation_failed: bool
    conflict_detected: bool
    conflict_agreement_level: str | None  # full / partial / conflicting
    unsupported_claims_removed: int
    # Warning flags (no raw content)
    stale_source_warning: bool
    stale_count: int
    ocr_warning: bool
    extraction_warning: bool
    processing_warning: bool
    evidence_quality_warning: bool
    # Retrieval counts (safe aggregates)
    citation_count: int
    retrieved_count: int
    # Optional Langfuse trace link
    langfuse_trace_id: str | None = None
    # Request ID for cross-referencing
    request_id: str | None = None


class TrustMetricsService:
    """Records trust metric snapshots as UsageEvent rows."""

    def __init__(self, usage_repository: UsageRepository | None = None) -> None:
        self._repo = usage_repository or UsageRepository()

    async def record(
        self,
        session: AsyncSession,
        snapshot: TrustMetricsSnapshot,
    ) -> None:
        """Persist a trust metrics snapshot. Never raises — failures are logged."""
        try:
            await self._record_unsafe(session, snapshot)
        except Exception as exc:
            _logger.debug(
                "trust_metrics.record_failed message_id=%s error=%s",
                snapshot.message_id,
                exc.__class__.__name__,
            )

    async def _record_unsafe(
        self,
        session: AsyncSession,
        snapshot: TrustMetricsSnapshot,
    ) -> None:
        metadata: dict[str, object] = {
            "message_id": snapshot.message_id,
            "session_id": snapshot.session_id,
            "trust_level": snapshot.trust_level,
            "confidence_score": snapshot.confidence_score,
            "confidence_category": snapshot.confidence_category,
            "citation_support_score": snapshot.citation_support_score,
            "verification_support_score": snapshot.verification_support_score,
            "not_found": snapshot.not_found,
            "citation_validation_failed": snapshot.citation_validation_failed,
            "conflict_detected": snapshot.conflict_detected,
            "conflict_agreement_level": snapshot.conflict_agreement_level,
            "unsupported_claims_removed": snapshot.unsupported_claims_removed,
            "stale_source_warning": snapshot.stale_source_warning,
            "stale_count": snapshot.stale_count,
            "ocr_warning": snapshot.ocr_warning,
            "extraction_warning": snapshot.extraction_warning,
            "processing_warning": snapshot.processing_warning,
            "evidence_quality_warning": snapshot.evidence_quality_warning,
            "citation_count": snapshot.citation_count,
            "retrieved_count": snapshot.retrieved_count,
        }
        if snapshot.langfuse_trace_id is not None:
            metadata["langfuse_trace_id"] = snapshot.langfuse_trace_id
        if snapshot.request_id is not None:
            metadata["request_id"] = snapshot.request_id

        await self._repo.create_usage_event(
            session,
            organization_id=snapshot.organization_id,
            user_id=snapshot.user_id,
            event_type=_TRUST_EVENT_TYPE,
            metadata=metadata,
            request_id=snapshot.request_id,
        )
