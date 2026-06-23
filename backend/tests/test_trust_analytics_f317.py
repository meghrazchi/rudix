"""Backend tests for F317: Trust panel observability, analytics, and evaluation fixtures.

Covers:
  A. TrustMetricsService — record emits a UsageEvent with correct metadata
  B. TrustMetricsService — record with Langfuse trace ID includes trace in metadata
  C. TrustMetricsService — record failures are suppressed (no exception propagates)
  D. TrustMetadataEvalCase — trust level match scoring (pass and fail)
  E. TrustMetadataEvalCase — not_found match scoring
  F. TrustMetadataEvalCase — citation support score threshold
  G. TrustMetadataEvalCase — confidence score range check
  H. TrustMetadataEvalCase — conflict and stale warning flags
  I. TrustMetadataEvalCase — overall_pass when no expectations provided
  J. ChatTraceMetadata — trust fields extend the dataclass defaults safely
  K. HTTP — GET /admin/trust-analytics requires admin/owner role (member gets 403)
  L. HTTP — GET /admin/trust-analytics returns telemetry_missing when no events
  M. HTTP — GET /admin/trust-analytics returns trust distribution from events
  N. HTTP — GET /admin/trust-analytics counts warning types correctly
  O. HTTP — GET /admin/trust-analytics date range filter excludes events outside range
  P. HTTP — GET /admin/trust-analytics from > to returns 400
  Q. HTTP — GET /admin/trust-analytics org isolation prevents cross-org data
  R. HTTP — GET /admin/trust-analytics computes correct not_found_rate
  S. HTTP — GET /admin/trust-analytics daily_trends has one entry per day in range
  T. HTTP — GET /admin/trust-analytics counts langfuse trace links

Run:
    pytest tests/test_trust_analytics_f317.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.core.langfuse_tracer import ChatTraceMetadata
from app.db.session import get_db_session
from app.domains.chat.services.trust_metrics_service import (
    TrustMetricsService,
    TrustMetricsSnapshot,
)
from app.domains.evaluations.services.evaluation_metrics_service import (
    TrustMetadataEvalCase,
    score_trust_metadata_case,
)
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import UsageEvent
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def trust_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "langfuse_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


def _token(user_id: str, org_id: str, role: str = OrganizationRole.admin.value) -> str:
    return create_app_access_token(
        user_id=user_id,
        organization_id=org_id,
        role=role,
        secret=SecretStr("test-secret"),
        issuer="rudix-test",
        audience="rudix-test-audience",
    )


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


async def _make_org_user(db: AsyncSession, role: str = OrganizationRole.admin.value) -> dict:
    slug = f"trust-org-{uuid4().hex[:8]}"
    org = Organization(name=f"Trust Org {slug}", slug=slug)
    db.add(org)
    await db.flush()

    user = User(email=f"trust-{uuid4().hex[:6]}@test.com", display_name="Trust User")
    db.add(user)
    await db.flush()

    member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    db.add(member)
    await db.flush()

    tok = _token(str(user.id), str(org.id), role)
    return {"org_id": str(org.id), "user_id": str(user.id), "token": tok}


def _trust_event(
    org_id,
    *,
    trust_level: str = "high",
    confidence_score: float = 0.85,
    citation_support_score: float = 0.9,
    not_found: bool = False,
    conflict_detected: bool = False,
    stale_source_warning: bool = False,
    ocr_warning: bool = False,
    extraction_warning: bool = False,
    processing_warning: bool = False,
    evidence_quality_warning: bool = False,
    citation_validation_failed: bool = False,
    unsupported_claims_removed: int = 0,
    langfuse_trace_id: str | None = None,
    created_at: datetime | None = None,
) -> UsageEvent:
    meta: dict = {
        "trust_level": trust_level,
        "confidence_score": confidence_score,
        "citation_support_score": citation_support_score,
        "not_found": not_found,
        "conflict_detected": conflict_detected,
        "stale_source_warning": stale_source_warning,
        "ocr_warning": ocr_warning,
        "extraction_warning": extraction_warning,
        "processing_warning": processing_warning,
        "evidence_quality_warning": evidence_quality_warning,
        "citation_validation_failed": citation_validation_failed,
        "unsupported_claims_removed": unsupported_claims_removed,
        "message_id": uuid4().hex,
        "session_id": uuid4().hex,
    }
    if langfuse_trace_id:
        meta["langfuse_trace_id"] = langfuse_trace_id
    event = UsageEvent(
        organization_id=org_id,
        event_type="trust.answer_metrics",
        metadata_json=meta,
    )
    if created_at is not None:
        event.created_at = created_at
    return event


# ---------------------------------------------------------------------------
# A. TrustMetricsService — record emits UsageEvent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_metrics_service_emits_usage_event(db_session: AsyncSession) -> None:
    org_id = uuid4()
    user_id = uuid4()
    service = TrustMetricsService()
    snapshot = TrustMetricsSnapshot(
        organization_id=org_id,
        user_id=user_id,
        message_id="msg-001",
        session_id="sess-001",
        trust_level="high",
        confidence_score=0.9,
        confidence_category="high",
        citation_support_score=0.88,
        verification_support_score=0.75,
        not_found=False,
        citation_validation_failed=False,
        conflict_detected=False,
        conflict_agreement_level=None,
        unsupported_claims_removed=0,
        stale_source_warning=False,
        stale_count=0,
        ocr_warning=False,
        extraction_warning=False,
        processing_warning=False,
        evidence_quality_warning=False,
        citation_count=3,
        retrieved_count=5,
    )
    await service.record(db_session, snapshot)
    await db_session.flush()

    from sqlalchemy import select

    stmt = select(UsageEvent).where(
        UsageEvent.organization_id == org_id,
        UsageEvent.event_type == "trust.answer_metrics",
    )
    events = list((await db_session.execute(stmt)).scalars().all())
    assert len(events) == 1
    meta = events[0].metadata_json
    assert meta["trust_level"] == "high"
    assert meta["confidence_score"] == pytest.approx(0.9)
    assert meta["message_id"] == "msg-001"
    assert meta["not_found"] is False


# ---------------------------------------------------------------------------
# B. TrustMetricsService — Langfuse trace ID stored when provided
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_metrics_service_stores_langfuse_trace_id(db_session: AsyncSession) -> None:
    org_id = uuid4()
    service = TrustMetricsService()
    snapshot = TrustMetricsSnapshot(
        organization_id=org_id,
        user_id=None,
        message_id="msg-002",
        session_id="sess-002",
        trust_level="medium",
        confidence_score=0.6,
        confidence_category="medium",
        citation_support_score=0.5,
        verification_support_score=None,
        not_found=False,
        citation_validation_failed=False,
        conflict_detected=False,
        conflict_agreement_level=None,
        unsupported_claims_removed=0,
        stale_source_warning=False,
        stale_count=0,
        ocr_warning=False,
        extraction_warning=False,
        processing_warning=False,
        evidence_quality_warning=False,
        citation_count=1,
        retrieved_count=2,
        langfuse_trace_id="trace-abc123",
    )
    await service.record(db_session, snapshot)
    await db_session.flush()

    from sqlalchemy import select

    stmt = select(UsageEvent).where(
        UsageEvent.organization_id == org_id,
        UsageEvent.event_type == "trust.answer_metrics",
    )
    events = list((await db_session.execute(stmt)).scalars().all())
    assert len(events) == 1
    assert events[0].metadata_json.get("langfuse_trace_id") == "trace-abc123"


# ---------------------------------------------------------------------------
# C. TrustMetricsService — failures suppressed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_metrics_service_suppresses_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domains.admin.repositories.usage import UsageRepository

    class BrokenRepo(UsageRepository):
        async def create_usage_event(self, *args, **kwargs):
            raise RuntimeError("DB exploded")

    service = TrustMetricsService(usage_repository=BrokenRepo())
    snapshot = TrustMetricsSnapshot(
        organization_id=uuid4(),
        user_id=None,
        message_id="msg-x",
        session_id="sess-x",
        trust_level="low",
        confidence_score=0.2,
        confidence_category="low",
        citation_support_score=0.1,
        verification_support_score=None,
        not_found=False,
        citation_validation_failed=False,
        conflict_detected=False,
        conflict_agreement_level=None,
        unsupported_claims_removed=0,
        stale_source_warning=False,
        stale_count=0,
        ocr_warning=False,
        extraction_warning=False,
        processing_warning=False,
        evidence_quality_warning=False,
        citation_count=0,
        retrieved_count=0,
    )
    # Must not raise
    from unittest.mock import MagicMock

    await service.record(MagicMock(), snapshot)


# ---------------------------------------------------------------------------
# D. TrustMetadataEvalCase — trust level match scoring
# ---------------------------------------------------------------------------


def test_eval_case_trust_level_match() -> None:
    case = TrustMetadataEvalCase(expected_trust_level="high")
    result = score_trust_metadata_case(
        case,
        actual_trust_level="high",
        actual_not_found=False,
        actual_citation_support_score=0.9,
        actual_confidence_score=0.85,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.trust_level_match is True
    assert result.overall_pass is True


def test_eval_case_trust_level_mismatch() -> None:
    case = TrustMetadataEvalCase(expected_trust_level="high")
    result = score_trust_metadata_case(
        case,
        actual_trust_level="low",
        actual_not_found=False,
        actual_citation_support_score=0.2,
        actual_confidence_score=0.3,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.trust_level_match is False
    assert result.overall_pass is False


# ---------------------------------------------------------------------------
# E. TrustMetadataEvalCase — not_found match scoring
# ---------------------------------------------------------------------------


def test_eval_case_not_found_match() -> None:
    case = TrustMetadataEvalCase(expected_not_found=True)
    result = score_trust_metadata_case(
        case,
        actual_trust_level="not_found",
        actual_not_found=True,
        actual_citation_support_score=None,
        actual_confidence_score=None,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.not_found_match is True
    assert result.overall_pass is True


# ---------------------------------------------------------------------------
# F. TrustMetadataEvalCase — citation support threshold
# ---------------------------------------------------------------------------


def test_eval_case_citation_support_threshold_pass() -> None:
    case = TrustMetadataEvalCase(min_citation_support_score=0.6)
    result = score_trust_metadata_case(
        case,
        actual_trust_level="high",
        actual_not_found=False,
        actual_citation_support_score=0.75,
        actual_confidence_score=0.8,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.citation_support_ok is True
    assert result.overall_pass is True


def test_eval_case_citation_support_threshold_fail() -> None:
    case = TrustMetadataEvalCase(min_citation_support_score=0.6)
    result = score_trust_metadata_case(
        case,
        actual_trust_level="low",
        actual_not_found=False,
        actual_citation_support_score=0.3,
        actual_confidence_score=0.4,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.citation_support_ok is False
    assert result.overall_pass is False


def test_eval_case_citation_support_none_fails_threshold() -> None:
    case = TrustMetadataEvalCase(min_citation_support_score=0.5)
    result = score_trust_metadata_case(
        case,
        actual_trust_level=None,
        actual_not_found=False,
        actual_citation_support_score=None,
        actual_confidence_score=None,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.citation_support_ok is False


# ---------------------------------------------------------------------------
# G. TrustMetadataEvalCase — confidence score range
# ---------------------------------------------------------------------------


def test_eval_case_confidence_range() -> None:
    case = TrustMetadataEvalCase(min_confidence_score=0.4, max_confidence_score=0.9)
    result = score_trust_metadata_case(
        case,
        actual_trust_level="medium",
        actual_not_found=False,
        actual_citation_support_score=0.7,
        actual_confidence_score=0.65,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.confidence_range_ok is True
    assert result.overall_pass is True


def test_eval_case_confidence_range_fail() -> None:
    case = TrustMetadataEvalCase(min_confidence_score=0.7)
    result = score_trust_metadata_case(
        case,
        actual_trust_level="low",
        actual_not_found=False,
        actual_citation_support_score=0.3,
        actual_confidence_score=0.4,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.confidence_range_ok is False
    assert result.overall_pass is False


# ---------------------------------------------------------------------------
# H. TrustMetadataEvalCase — conflict and stale warning flags
# ---------------------------------------------------------------------------


def test_eval_case_conflict_and_stale_flags() -> None:
    case = TrustMetadataEvalCase(expected_conflict_detected=True, expected_stale_warning=False)
    result = score_trust_metadata_case(
        case,
        actual_trust_level="warning",
        actual_not_found=False,
        actual_citation_support_score=0.5,
        actual_confidence_score=0.5,
        actual_conflict_detected=True,
        actual_stale_warning=False,
    )
    assert result.conflict_match is True
    assert result.stale_warning_match is True
    assert result.overall_pass is True


# ---------------------------------------------------------------------------
# I. TrustMetadataEvalCase — overall_pass when no expectations
# ---------------------------------------------------------------------------


def test_eval_case_no_expectations_overall_pass() -> None:
    case = TrustMetadataEvalCase()
    result = score_trust_metadata_case(
        case,
        actual_trust_level="low",
        actual_not_found=False,
        actual_citation_support_score=0.2,
        actual_confidence_score=0.3,
        actual_conflict_detected=False,
        actual_stale_warning=False,
    )
    assert result.overall_pass is True
    assert result.trust_level_match is None
    assert result.not_found_match is None


# ---------------------------------------------------------------------------
# J. ChatTraceMetadata — trust fields extend the dataclass
# ---------------------------------------------------------------------------


def test_chat_trace_metadata_trust_fields_defaults() -> None:
    meta = ChatTraceMetadata(
        organization_id="org-1",
        user_id="user-1",
        session_id="sess-1",
        message_id="msg-1",
        question="test?",
        answer="answer.",
        scope_mode="all",
    )
    assert meta.trust_level is None
    assert meta.trust_citation_support_score is None
    assert meta.trust_unsupported_claims_removed == 0
    assert meta.trust_stale_source_warning is False
    assert meta.trust_conflict_detected is False
    assert meta.trust_ocr_warning is False
    assert meta.trust_extraction_warning is False
    assert meta.trust_evidence_quality_warning is False


def test_chat_trace_metadata_trust_fields_set() -> None:
    meta = ChatTraceMetadata(
        organization_id="org-1",
        user_id="user-1",
        session_id="sess-1",
        message_id="msg-1",
        question="test?",
        answer="answer.",
        scope_mode="all",
        trust_level="medium",
        trust_citation_support_score=0.72,
        trust_unsupported_claims_removed=2,
        trust_stale_source_warning=True,
        trust_conflict_detected=False,
        trust_ocr_warning=True,
        trust_extraction_warning=False,
        trust_evidence_quality_warning=True,
    )
    assert meta.trust_level == "medium"
    assert meta.trust_citation_support_score == pytest.approx(0.72)
    assert meta.trust_unsupported_claims_removed == 2
    assert meta.trust_stale_source_warning is True
    assert meta.trust_ocr_warning is True
    assert meta.trust_evidence_quality_warning is True


# ---------------------------------------------------------------------------
# K. HTTP — role guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_member_gets_403(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session, role=OrganizationRole.member.value)
    resp = await trust_client.get(
        "/api/admin/trust-analytics", headers=_auth(ctx["token"])
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# L. HTTP — telemetry_missing when no events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_empty_org_telemetry_missing(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await trust_client.get(
        "/api/admin/trust-analytics", headers=_auth(ctx["token"])
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_answers"] == 0
    assert data["telemetry_missing"] is True


# ---------------------------------------------------------------------------
# M. HTTP — trust distribution from events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_distribution(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    for _ in range(3):
        db_session.add(_trust_event(org_id, trust_level="high"))
    for _ in range(2):
        db_session.add(_trust_event(org_id, trust_level="medium"))
    db_session.add(_trust_event(org_id, trust_level="low"))
    await db_session.flush()

    resp = await trust_client.get(
        "/api/admin/trust-analytics", headers=_auth(ctx["token"])
    )
    assert resp.status_code == 200
    dist = resp.json()["trust_distribution"]
    assert dist["high_count"] == 3
    assert dist["medium_count"] == 2
    assert dist["low_count"] == 1
    assert dist["not_found_count"] == 0


# ---------------------------------------------------------------------------
# N. HTTP — warning counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_warning_counts(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_trust_event(org_id, stale_source_warning=True))
    db_session.add(_trust_event(org_id, ocr_warning=True, conflict_detected=True))
    db_session.add(_trust_event(org_id, extraction_warning=True))
    db_session.add(_trust_event(org_id, trust_level="high"))
    await db_session.flush()

    resp = await trust_client.get(
        "/api/admin/trust-analytics", headers=_auth(ctx["token"])
    )
    assert resp.status_code == 200
    w = resp.json()["warnings"]
    assert w["stale_source_count"] == 1
    assert w["ocr_count"] == 1
    assert w["conflict_count"] == 1
    assert w["extraction_count"] == 1


# ---------------------------------------------------------------------------
# O. HTTP — date range filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_date_range_filter(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    in_range = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    out_of_range = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

    db_session.add(_trust_event(org_id, trust_level="high", created_at=in_range))
    db_session.add(_trust_event(org_id, trust_level="low", created_at=out_of_range))
    await db_session.flush()

    resp = await trust_client.get(
        "/api/admin/trust-analytics",
        headers=_auth(ctx["token"]),
        params={"from": "2026-06-01", "to": "2026-06-30"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_answers"] == 1
    assert data["trust_distribution"]["high_count"] == 1


# ---------------------------------------------------------------------------
# P. HTTP — from > to returns 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_invalid_date_range(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await trust_client.get(
        "/api/admin/trust-analytics",
        headers=_auth(ctx["token"]),
        params={"from": "2026-06-30", "to": "2026-06-01"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Q. HTTP — org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_org_isolation(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx_a = await _make_org_user(db_session)
    ctx_b = await _make_org_user(db_session)

    db_session.add(_trust_event(ctx_b["org_id"], trust_level="high"))
    db_session.add(_trust_event(ctx_b["org_id"], trust_level="medium"))
    await db_session.flush()

    resp = await trust_client.get(
        "/api/admin/trust-analytics", headers=_auth(ctx_a["token"])
    )
    assert resp.status_code == 200
    assert resp.json()["total_answers"] == 0


# ---------------------------------------------------------------------------
# R. HTTP — not_found_rate computed correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_not_found_rate(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_trust_event(org_id, not_found=True, trust_level="not_found"))
    db_session.add(_trust_event(org_id, not_found=True, trust_level="not_found"))
    db_session.add(_trust_event(org_id, trust_level="high"))
    db_session.add(_trust_event(org_id, trust_level="high"))
    await db_session.flush()

    resp = await trust_client.get(
        "/api/admin/trust-analytics", headers=_auth(ctx["token"])
    )
    data = resp.json()
    assert data["total_answers"] == 4
    assert data["not_found_rate"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# S. HTTP — daily_trends has one entry per day in range
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_daily_trends_structure(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    resp = await trust_client.get(
        "/api/admin/trust-analytics",
        headers=_auth(ctx["token"]),
        params={"from": "2026-06-01", "to": "2026-06-07"},
    )
    assert resp.status_code == 200
    trends = resp.json()["daily_trends"]
    assert len(trends) == 7
    assert trends[0]["date"] == "2026-06-01"
    assert trends[-1]["date"] == "2026-06-07"
    for point in trends:
        assert "answer_count" in point
        assert "not_found_count" in point


# ---------------------------------------------------------------------------
# T. HTTP — counts Langfuse trace links
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_analytics_langfuse_trace_links(
    trust_client: AsyncClient, db_session: AsyncSession
) -> None:
    ctx = await _make_org_user(db_session)
    org_id = ctx["org_id"]

    db_session.add(_trust_event(org_id, langfuse_trace_id="trace-001"))
    db_session.add(_trust_event(org_id, langfuse_trace_id="trace-002"))
    db_session.add(_trust_event(org_id))  # no trace
    await db_session.flush()

    resp = await trust_client.get(
        "/api/admin/trust-analytics", headers=_auth(ctx["token"])
    )
    assert resp.status_code == 200
    langfuse = resp.json()["langfuse"]
    assert langfuse["traces_linked_count"] == 2
