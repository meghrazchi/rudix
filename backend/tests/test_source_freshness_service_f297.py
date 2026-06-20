"""Unit tests for SourceFreshnessService — F297."""

from __future__ import annotations

import os
from datetime import date
from uuid import UUID, uuid4

import pytest

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

from app.domains.chat.services.source_freshness_service import (
    EXCLUDED_BY_DEFAULT,
    TRUST_SCORE_MULTIPLIERS,
    DocumentTrustData,
    SourceFreshnessService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeDoc:
    """Minimal duck-typed Document for trust map building."""

    def __init__(
        self,
        *,
        doc_id: UUID | None = None,
        trust_status: str = "current",
        version_label: str | None = None,
        review_date: date | None = None,
        effective_date: date | None = None,
        stale_after_days: int | None = None,
        superseded_by_document_id: UUID | None = None,
    ) -> None:
        self.id = doc_id or uuid4()
        self.trust_status = trust_status
        self.version_label = version_label
        self.review_date = review_date
        self.effective_date = effective_date
        self.stale_after_days = stale_after_days
        self.superseded_by_document_id = superseded_by_document_id


_TODAY = date(2026, 6, 15)
_YESTERDAY = date(2026, 6, 14)
_TOMORROW = date(2026, 6, 16)

svc = SourceFreshnessService()


# ---------------------------------------------------------------------------
# Trust map building
# ---------------------------------------------------------------------------


def test_build_trust_map_basic() -> None:
    doc = _FakeDoc(trust_status="verified", version_label="v2")
    trust_map = svc.build_trust_map([doc])
    assert str(doc.id) in trust_map
    trust = trust_map[str(doc.id)]
    assert trust.trust_status == "verified"
    assert trust.version_label == "v2"


def test_build_trust_map_skips_missing_id() -> None:
    class BadDoc:
        id = None
        trust_status = "current"
        version_label = None
        review_date = None
        effective_date = None
        stale_after_days = None
        superseded_by_document_id = None

    trust_map = svc.build_trust_map([BadDoc()])
    assert trust_map == {}


def test_build_trust_map_multiple() -> None:
    docs = [_FakeDoc(trust_status=s) for s in ("current", "verified", "deprecated")]
    trust_map = svc.build_trust_map(docs)
    assert len(trust_map) == 3


# ---------------------------------------------------------------------------
# Effective trust status
# ---------------------------------------------------------------------------


def test_effective_status_current_before_review_date() -> None:
    trust = DocumentTrustData(
        document_id=uuid4(),
        trust_status="current",
        review_date=_TOMORROW,
    )
    assert svc.compute_effective_trust_status(trust, today=_TODAY) == "current"


def test_effective_status_becomes_stale_after_review_date() -> None:
    trust = DocumentTrustData(
        document_id=uuid4(),
        trust_status="current",
        review_date=_YESTERDAY,
    )
    assert svc.compute_effective_trust_status(trust, today=_TODAY) == "stale"


def test_effective_status_verified_becomes_stale_past_review() -> None:
    trust = DocumentTrustData(
        document_id=uuid4(),
        trust_status="verified",
        review_date=_YESTERDAY,
    )
    assert svc.compute_effective_trust_status(trust, today=_TODAY) == "stale"


def test_effective_status_deprecated_unchanged() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="deprecated")
    assert svc.compute_effective_trust_status(trust, today=_TODAY) == "deprecated"


def test_effective_status_superseded_unchanged() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="superseded")
    assert svc.compute_effective_trust_status(trust, today=_TODAY) == "superseded"


def test_effective_status_expired_unchanged() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="expired")
    assert svc.compute_effective_trust_status(trust, today=_TODAY) == "expired"


def test_effective_status_stale_unchanged() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="stale")
    assert svc.compute_effective_trust_status(trust, today=_TODAY) == "stale"


def test_effective_status_no_review_date_stays_current() -> None:
    trust = DocumentTrustData(document_id=uuid4(), trust_status="current")
    assert svc.compute_effective_trust_status(trust, today=_TODAY) == "current"


# ---------------------------------------------------------------------------
# Filter excluded
# ---------------------------------------------------------------------------


def test_filter_excludes_deprecated_by_default() -> None:
    doc = _FakeDoc(trust_status="deprecated")
    trust_map = svc.build_trust_map([doc])
    result = svc.filter_excluded(
        chunk_document_ids=[str(doc.id)],
        trust_map=trust_map,
        exclude_deprecated=True,
        today=_TODAY,
    )
    assert str(doc.id) in result.excluded_document_ids
    assert result.excluded_count == 1


def test_filter_excludes_superseded() -> None:
    doc = _FakeDoc(trust_status="superseded")
    trust_map = svc.build_trust_map([doc])
    result = svc.filter_excluded(
        chunk_document_ids=[str(doc.id)],
        trust_map=trust_map,
        exclude_deprecated=True,
        today=_TODAY,
    )
    assert str(doc.id) in result.excluded_document_ids


def test_filter_excludes_expired() -> None:
    doc = _FakeDoc(trust_status="expired")
    trust_map = svc.build_trust_map([doc])
    result = svc.filter_excluded(
        chunk_document_ids=[str(doc.id)],
        trust_map=trust_map,
        exclude_deprecated=True,
        today=_TODAY,
    )
    assert str(doc.id) in result.excluded_document_ids


def test_filter_keeps_current() -> None:
    doc = _FakeDoc(trust_status="current")
    trust_map = svc.build_trust_map([doc])
    result = svc.filter_excluded(
        chunk_document_ids=[str(doc.id)],
        trust_map=trust_map,
        exclude_deprecated=True,
        today=_TODAY,
    )
    assert str(doc.id) not in result.excluded_document_ids
    assert result.excluded_count == 0


def test_filter_keeps_verified() -> None:
    doc = _FakeDoc(trust_status="verified")
    trust_map = svc.build_trust_map([doc])
    result = svc.filter_excluded(
        chunk_document_ids=[str(doc.id)],
        trust_map=trust_map,
        exclude_deprecated=True,
        today=_TODAY,
    )
    assert str(doc.id) not in result.excluded_document_ids


def test_filter_marks_past_review_date_as_stale() -> None:
    doc = _FakeDoc(trust_status="current", review_date=_YESTERDAY)
    trust_map = svc.build_trust_map([doc])
    result = svc.filter_excluded(
        chunk_document_ids=[str(doc.id)],
        trust_map=trust_map,
        exclude_deprecated=True,
        today=_TODAY,
    )
    assert str(doc.id) not in result.excluded_document_ids
    assert str(doc.id) in result.stale_document_ids


def test_filter_exclude_false_keeps_all_statuses() -> None:
    docs = [
        _FakeDoc(trust_status="deprecated"),
        _FakeDoc(trust_status="superseded"),
        _FakeDoc(trust_status="expired"),
    ]
    trust_map = svc.build_trust_map(docs)
    result = svc.filter_excluded(
        chunk_document_ids=[str(d.id) for d in docs],
        trust_map=trust_map,
        exclude_deprecated=False,
        today=_TODAY,
    )
    assert result.excluded_count == 0
    assert result.excluded_document_ids == frozenset()


def test_filter_unknown_doc_not_excluded() -> None:
    unknown_id = str(uuid4())
    result = svc.filter_excluded(
        chunk_document_ids=[unknown_id],
        trust_map={},
        exclude_deprecated=True,
        today=_TODAY,
    )
    assert result.excluded_count == 0


# ---------------------------------------------------------------------------
# Score multiplier
# ---------------------------------------------------------------------------


def test_multiplier_verified_boosts() -> None:
    doc = _FakeDoc(trust_status="verified")
    trust_map = svc.build_trust_map([doc])
    adjusted = svc.apply_trust_score_multiplier(
        score=0.8,
        document_id=str(doc.id),
        trust_map=trust_map,
        today=_TODAY,
    )
    assert adjusted == pytest.approx(0.8 * TRUST_SCORE_MULTIPLIERS["verified"])


def test_multiplier_current_unchanged() -> None:
    doc = _FakeDoc(trust_status="current")
    trust_map = svc.build_trust_map([doc])
    adjusted = svc.apply_trust_score_multiplier(
        score=0.8,
        document_id=str(doc.id),
        trust_map=trust_map,
        today=_TODAY,
    )
    assert adjusted == pytest.approx(0.8)


def test_multiplier_deprecated_reduced() -> None:
    doc = _FakeDoc(trust_status="deprecated")
    trust_map = svc.build_trust_map([doc])
    adjusted = svc.apply_trust_score_multiplier(
        score=1.0,
        document_id=str(doc.id),
        trust_map=trust_map,
        today=_TODAY,
    )
    assert adjusted == pytest.approx(TRUST_SCORE_MULTIPLIERS["deprecated"])


def test_multiplier_stale_by_review_date() -> None:
    doc = _FakeDoc(trust_status="current", review_date=_YESTERDAY)
    trust_map = svc.build_trust_map([doc])
    adjusted = svc.apply_trust_score_multiplier(
        score=1.0,
        document_id=str(doc.id),
        trust_map=trust_map,
        today=_TODAY,
    )
    assert adjusted == pytest.approx(TRUST_SCORE_MULTIPLIERS["stale"])


def test_multiplier_unknown_doc_unchanged() -> None:
    adjusted = svc.apply_trust_score_multiplier(
        score=0.75,
        document_id=str(uuid4()),
        trust_map={},
        today=_TODAY,
    )
    assert adjusted == pytest.approx(0.75)


def test_multiplier_draft_slightly_reduced() -> None:
    doc = _FakeDoc(trust_status="draft")
    trust_map = svc.build_trust_map([doc])
    adjusted = svc.apply_trust_score_multiplier(
        score=1.0,
        document_id=str(doc.id),
        trust_map=trust_map,
        today=_TODAY,
    )
    assert adjusted == pytest.approx(TRUST_SCORE_MULTIPLIERS["draft"])


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_excluded_by_default_set() -> None:
    assert "deprecated" in EXCLUDED_BY_DEFAULT
    assert "superseded" in EXCLUDED_BY_DEFAULT
    assert "expired" in EXCLUDED_BY_DEFAULT
    assert "current" not in EXCLUDED_BY_DEFAULT
    assert "verified" not in EXCLUDED_BY_DEFAULT


def test_all_statuses_have_multiplier() -> None:
    for status in ("draft", "current", "verified", "stale", "deprecated", "superseded", "expired"):
        assert status in TRUST_SCORE_MULTIPLIERS


def test_verified_highest_multiplier() -> None:
    assert TRUST_SCORE_MULTIPLIERS["verified"] > TRUST_SCORE_MULTIPLIERS["current"]


def test_excluded_statuses_have_lowest_multipliers() -> None:
    for excl in EXCLUDED_BY_DEFAULT:
        assert TRUST_SCORE_MULTIPLIERS[excl] < TRUST_SCORE_MULTIPLIERS["current"]
