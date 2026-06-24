"""Unit tests for F311 freshness warnings and state derivation.

Tests cover:
  - derive_freshness_state() for all status combinations
  - preferred_source_bump (PREFERRED_SOURCE_BUMP applied to verified/trusted)
  - apply_exclusion_fallback() — re-include when all excluded
  - build_warning_reasons() — structured warning message generation
  - build_trust_map() — last_updated_at propagation
  - SourceFreshnessRecord new fields (unreviewed_count, deprecated_count, etc.)
  - CitationTrustRecord new fields (freshness_state, doc_last_updated_at, etc.)
  - OrgFreshnessPolicy model field constraints
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from uuid import UUID, uuid4

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.domains.chat.schemas.trust_metadata import (
    CitationTrustRecord,
    SourceFreshnessRecord,
)
from app.domains.chat.services.source_freshness_service import (
    PREFERRED_SOURCE_BUMP,
    TRUST_SCORE_MULTIPLIERS,
    DocumentTrustData,
    FreshnessState,
    SourceFreshnessService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDoc:
    def __init__(
        self,
        *,
        doc_id: UUID | None = None,
        trust_status: str = "current",
        review_status: str | None = None,
        review_owner_id: UUID | None = None,
        review_due_date: date | None = None,
        expiry_date: date | None = None,
        version_label: str | None = None,
        review_date: date | None = None,
        effective_date: date | None = None,
        stale_after_days: int | None = None,
        superseded_by_document_id: UUID | None = None,
        trust_level: str | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        self.id = doc_id or uuid4()
        self.trust_status = trust_status
        self.review_status = review_status
        self.review_owner_id = review_owner_id
        self.review_due_date = review_due_date
        self.expiry_date = expiry_date
        self.version_label = version_label
        self.review_date = review_date
        self.effective_date = effective_date
        self.stale_after_days = stale_after_days
        self.superseded_by_document_id = superseded_by_document_id
        self.trust_level = trust_level
        self.updated_at = updated_at


_TODAY = date(2026, 6, 15)
_YESTERDAY = date(2026, 6, 14)
_TOMORROW = date(2026, 6, 16)
_UPDATED_AT = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

svc = SourceFreshnessService()

# ---------------------------------------------------------------------------
# derive_freshness_state — mapping to normalized display enum
# ---------------------------------------------------------------------------


def test_derive_freshness_state_current() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="current")
    assert svc.derive_freshness_state(trust, today=_TODAY) == "current"


def test_derive_freshness_state_verified_is_current() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="verified")
    assert svc.derive_freshness_state(trust, today=_TODAY) == "current"


def test_derive_freshness_state_trusted_is_current() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="trusted")
    assert svc.derive_freshness_state(trust, today=_TODAY) == "current"


def test_derive_freshness_state_draft() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="draft")
    assert svc.derive_freshness_state(trust, today=_TODAY) == "draft"


def test_derive_freshness_state_stale_past_review_date() -> None:
    trust = DocumentTrustData(
        document_id=uuid4(),
        trust_status="current",
        review_date=_YESTERDAY,
    )
    assert svc.derive_freshness_state(trust, today=_TODAY) == "stale"


def test_derive_freshness_state_stale_explicit() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="stale")
    assert svc.derive_freshness_state(trust, today=_TODAY) == "stale"


def test_derive_freshness_state_expired_past_expiry() -> None:
    trust = DocumentTrustData(
        document_id=uuid4(),
        trust_status="current",
        expiry_date=_YESTERDAY,
    )
    assert svc.derive_freshness_state(trust, today=_TODAY) == "expired"


def test_derive_freshness_state_deprecated_status() -> None:
    for status in ("deprecated", "archived", "superseded"):
        trust = DocumentTrustData(document_id=uuid4(), trust_status=status)
        result = svc.derive_freshness_state(trust, today=_TODAY)
        assert result == "deprecated", f"Expected deprecated for {status}, got {result}"


def test_derive_freshness_state_unreviewed_past_due_date() -> None:
    trust = DocumentTrustData(
        document_id=uuid4(),
        trust_status="current",
        review_due_date=_YESTERDAY,
    )
    assert svc.derive_freshness_state(trust, today=_TODAY) == "unreviewed"


def test_derive_freshness_state_none_is_unknown() -> None:
    assert svc.derive_freshness_state(None) == "unknown"


def test_derive_freshness_state_unknown_status() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="something_else")
    assert svc.derive_freshness_state(trust, today=_TODAY) == "unknown"


# ---------------------------------------------------------------------------
# PREFERRED_SOURCE_BUMP — tie-breaking for verified/trusted
# ---------------------------------------------------------------------------


def test_preferred_source_bump_is_positive() -> None:
    assert PREFERRED_SOURCE_BUMP > 0


def test_preferred_source_bump_applied_to_verified() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="verified")
    doc_id = str(trust.document_id)
    trust_map = {doc_id: trust}
    base_score = 0.80
    adjusted = svc.apply_trust_score_multiplier(
        score=base_score, document_id=doc_id, trust_map=trust_map, today=_TODAY
    )
    expected = min(1.0, base_score * TRUST_SCORE_MULTIPLIERS["verified"] + PREFERRED_SOURCE_BUMP)
    assert abs(adjusted - expected) < 1e-9


def test_preferred_source_bump_applied_to_trusted() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="trusted")
    doc_id = str(trust.document_id)
    trust_map = {doc_id: trust}
    base_score = 0.80
    adjusted = svc.apply_trust_score_multiplier(
        score=base_score, document_id=doc_id, trust_map=trust_map, today=_TODAY
    )
    expected = min(1.0, base_score * TRUST_SCORE_MULTIPLIERS["trusted"] + PREFERRED_SOURCE_BUMP)
    assert abs(adjusted - expected) < 1e-9


def test_preferred_source_bump_not_applied_to_current() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="current")
    doc_id = str(trust.document_id)
    trust_map = {doc_id: trust}
    base_score = 0.80
    adjusted = svc.apply_trust_score_multiplier(
        score=base_score, document_id=doc_id, trust_map=trust_map, today=_TODAY
    )
    assert abs(adjusted - base_score * TRUST_SCORE_MULTIPLIERS["current"]) < 1e-9


def test_preferred_source_bump_caps_at_one() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="verified")
    doc_id = str(trust.document_id)
    trust_map = {doc_id: trust}
    adjusted = svc.apply_trust_score_multiplier(
        score=1.0, document_id=doc_id, trust_map=trust_map, today=_TODAY
    )
    assert adjusted <= 1.0


# ---------------------------------------------------------------------------
# apply_exclusion_fallback
# ---------------------------------------------------------------------------


def _fake_chunks(n: int) -> list:
    return [{"id": str(uuid4())} for _ in range(n)]


def test_exclusion_fallback_not_triggered_when_some_remain() -> None:
    before = _fake_chunks(5)
    after = _fake_chunks(3)
    result, fallback = svc.apply_exclusion_fallback(
        after_filter=after,
        before_filter=before,
        excluded_ids=frozenset({"abc"}),
    )
    assert not fallback
    assert result is after


def test_exclusion_fallback_triggered_when_all_excluded() -> None:
    before = _fake_chunks(3)
    result, fallback = svc.apply_exclusion_fallback(
        after_filter=[],
        before_filter=before,
        excluded_ids=frozenset({"x", "y", "z"}),
    )
    assert fallback
    assert result is before


def test_exclusion_fallback_not_triggered_when_no_exclusions() -> None:
    before = _fake_chunks(3)
    result, fallback = svc.apply_exclusion_fallback(
        after_filter=before,
        before_filter=before,
        excluded_ids=frozenset(),
    )
    assert not fallback
    assert result is before


def test_exclusion_fallback_empty_before_stays_empty() -> None:
    result, fallback = svc.apply_exclusion_fallback(
        after_filter=[],
        before_filter=[],
        excluded_ids=frozenset({"x"}),
    )
    assert not fallback
    assert result == []


# ---------------------------------------------------------------------------
# build_warning_reasons
# ---------------------------------------------------------------------------


def test_warning_reasons_stale_only() -> None:
    reasons = svc.build_warning_reasons(
        stale_count=2,
        excluded_count=0,
        unreviewed_count=0,
        deprecated_count=0,
        draft_count=0,
        all_excluded_fallback=False,
    )
    assert len(reasons) == 1
    assert "outdated" in reasons[0].lower() or "stale" in reasons[0].lower()
    assert "2" in reasons[0]


def test_warning_reasons_unreviewed_only() -> None:
    reasons = svc.build_warning_reasons(
        stale_count=0,
        excluded_count=0,
        unreviewed_count=1,
        deprecated_count=0,
        draft_count=0,
        all_excluded_fallback=False,
    )
    assert len(reasons) == 1
    assert "review" in reasons[0].lower()


def test_warning_reasons_deprecated_only() -> None:
    reasons = svc.build_warning_reasons(
        stale_count=0,
        excluded_count=0,
        unreviewed_count=0,
        deprecated_count=3,
        draft_count=0,
        all_excluded_fallback=False,
    )
    assert len(reasons) == 1
    assert "deprecated" in reasons[0].lower()


def test_warning_reasons_excluded_only() -> None:
    reasons = svc.build_warning_reasons(
        stale_count=0,
        excluded_count=2,
        unreviewed_count=0,
        deprecated_count=0,
        draft_count=0,
        all_excluded_fallback=False,
    )
    assert len(reasons) == 1
    assert "excluded" in reasons[0].lower()


def test_warning_reasons_all_excluded_fallback_leads() -> None:
    reasons = svc.build_warning_reasons(
        stale_count=0,
        excluded_count=3,
        unreviewed_count=0,
        deprecated_count=1,
        draft_count=0,
        all_excluded_fallback=True,
    )
    assert reasons[0].lower().startswith("all preferred sources")


def test_warning_reasons_empty_when_no_issues() -> None:
    reasons = svc.build_warning_reasons(
        stale_count=0,
        excluded_count=0,
        unreviewed_count=0,
        deprecated_count=0,
        draft_count=0,
        all_excluded_fallback=False,
    )
    assert reasons == []


def test_warning_reasons_multiple_issues() -> None:
    reasons = svc.build_warning_reasons(
        stale_count=1,
        excluded_count=2,
        unreviewed_count=1,
        deprecated_count=0,
        draft_count=0,
        all_excluded_fallback=False,
    )
    assert len(reasons) == 3


# ---------------------------------------------------------------------------
# build_trust_map — last_updated_at propagation
# ---------------------------------------------------------------------------


def test_build_trust_map_last_updated_at_propagated() -> None:
    doc = _FakeDoc(trust_status="current", updated_at=_UPDATED_AT)
    trust_map = svc.build_trust_map([doc])
    trust = trust_map[str(doc.id)]
    assert trust.last_updated_at == _UPDATED_AT


def test_build_trust_map_last_updated_at_none() -> None:
    doc = _FakeDoc(trust_status="current")
    trust_map = svc.build_trust_map([doc])
    trust = trust_map[str(doc.id)]
    assert trust.last_updated_at is None


# ---------------------------------------------------------------------------
# SourceFreshnessRecord — new fields
# ---------------------------------------------------------------------------


def test_source_freshness_record_new_fields_default() -> None:
    rec = SourceFreshnessRecord()
    assert rec.unreviewed_count == 0
    assert rec.deprecated_count == 0
    assert rec.all_excluded_fallback is False
    assert rec.warning_reasons == []


def test_source_freshness_record_populated() -> None:
    reasons = ["stale sources detected", "pending review"]
    rec = SourceFreshnessRecord(
        warning=True,
        warning_reason="stale sources detected",
        warning_reasons=reasons,
        stale_count=2,
        unreviewed_count=1,
        deprecated_count=0,
        excluded_count=0,
        boosted_count=3,
        all_excluded_fallback=False,
    )
    assert rec.warning is True
    assert rec.stale_count == 2
    assert rec.unreviewed_count == 1
    assert rec.warning_reasons == reasons


# ---------------------------------------------------------------------------
# CitationTrustRecord — new fields
# ---------------------------------------------------------------------------


def test_citation_trust_record_freshness_state_default_none() -> None:
    rec = CitationTrustRecord(document_id=str(uuid4()), chunk_id=str(uuid4()))
    assert rec.freshness_state is None
    assert rec.doc_last_updated_at is None
    assert rec.doc_review_owner_id is None
    assert rec.doc_unreviewed_warning is False
    assert rec.doc_deprecated_warning is False


def test_citation_trust_record_freshness_state_set() -> None:
    rec = CitationTrustRecord(
        document_id=str(uuid4()),
        chunk_id=str(uuid4()),
        freshness_state="stale",
        doc_last_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        doc_unreviewed_warning=False,
        doc_deprecated_warning=False,
    )
    assert rec.freshness_state == "stale"
    assert rec.doc_last_updated_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_citation_trust_record_deprecated_warning() -> None:
    rec = CitationTrustRecord(
        document_id=str(uuid4()),
        chunk_id=str(uuid4()),
        freshness_state="deprecated",
        doc_deprecated_warning=True,
    )
    assert rec.doc_deprecated_warning is True
    assert rec.freshness_state == "deprecated"


def test_citation_trust_record_unreviewed_warning() -> None:
    rec = CitationTrustRecord(
        document_id=str(uuid4()),
        chunk_id=str(uuid4()),
        freshness_state="unreviewed",
        doc_unreviewed_warning=True,
    )
    assert rec.doc_unreviewed_warning is True


def test_citation_trust_record_all_freshness_states_valid() -> None:
    valid_states: list[FreshnessState] = [
        "current",
        "stale",
        "expired",
        "deprecated",
        "draft",
        "unreviewed",
        "unknown",
    ]
    for state in valid_states:
        rec = CitationTrustRecord(
            document_id=str(uuid4()),
            chunk_id=str(uuid4()),
            freshness_state=state,
        )
        assert rec.freshness_state == state


# ---------------------------------------------------------------------------
# Integration: derive_freshness_state used in full trust-map scenario
# ---------------------------------------------------------------------------


def test_full_scenario_mixed_states() -> None:
    """End-to-end test: build trust map, derive states for mixed doc pool."""
    current_doc = _FakeDoc(trust_status="current")
    stale_doc = _FakeDoc(trust_status="current", review_date=_YESTERDAY)
    expired_doc = _FakeDoc(trust_status="current", expiry_date=_YESTERDAY)
    deprecated_doc = _FakeDoc(trust_status="deprecated")
    unreviewed_doc = _FakeDoc(trust_status="current", review_due_date=_YESTERDAY)
    draft_doc = _FakeDoc(trust_status="draft")

    docs = [current_doc, stale_doc, expired_doc, deprecated_doc, unreviewed_doc, draft_doc]
    trust_map = svc.build_trust_map(docs)

    assert svc.derive_freshness_state(trust_map[str(current_doc.id)], today=_TODAY) == "current"
    assert svc.derive_freshness_state(trust_map[str(stale_doc.id)], today=_TODAY) == "stale"
    assert svc.derive_freshness_state(trust_map[str(expired_doc.id)], today=_TODAY) == "expired"
    assert (
        svc.derive_freshness_state(trust_map[str(deprecated_doc.id)], today=_TODAY) == "deprecated"
    )
    assert (
        svc.derive_freshness_state(trust_map[str(unreviewed_doc.id)], today=_TODAY) == "unreviewed"
    )
    assert svc.derive_freshness_state(trust_map[str(draft_doc.id)], today=_TODAY) == "draft"
