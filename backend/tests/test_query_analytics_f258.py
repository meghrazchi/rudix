"""Backend tests for F258: Query analytics and knowledge-gap dashboard.

Covers:
  A. Service — summary returns zeros when no data
  B. Service — summary counts unanswered and low-confidence correctly
  C. Service — summary computes negative feedback rate from MessageFeedback
  D. Service — disabled when feature flag is off
  E. Service — trends returns one point per day in range
  F. Service — gap creation stores redacted text when policy is on
  G. Service — detect_gaps creates low_confidence gap when threshold breached
  H. Service — detect_gaps skips duplicate (same type+label already open)
  I. Service — convert_gap sets converted_to and status=in_review
  J. HTTP — GET /admin/query-analytics/summary requires admin role
  K. HTTP — GET /admin/query-analytics/summary returns 200 for admin
  L. HTTP — GET /admin/query-analytics/gaps returns paginated gap list
  M. HTTP — POST /admin/query-analytics/gaps creates gap (admin)
  N. HTTP — PATCH /admin/query-analytics/gaps/{id} updates status
  O. HTTP — POST /admin/query-analytics/gaps/{id}/convert returns conversion

Run:
    pytest tests/test_query_analytics_f258.py -v
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
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

from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.query_analytics.services.query_analytics_service import QueryAnalyticsService
from app.main import app
from app.models.chat import ChatMessage, ChatSession
from app.models.enums import OrganizationRole
from app.models.message_feedback import MessageFeedback
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db(db_session: AsyncSession) -> AsyncSession:
    return db_session


def _token(user_id: str, org_id: str, role: str) -> str:
    settings.auth_provider = AuthProvider.app
    return create_app_access_token(user_id=user_id, organization_id=org_id, role=role)


@pytest_asyncio.fixture
async def org(db: AsyncSession) -> Organization:
    o = Organization(name="AnalyticsOrg", slug=f"analytics-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def other_org(db: AsyncSession) -> Organization:
    o = Organization(name="OtherOrg", slug=f"other-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(
        id=uuid4(),
        email=f"admin-{uuid4().hex[:6]}@test.com",
        hashed_password="x",
        organization_id=org.id,
    )
    db.add(u)
    member = OrganizationMember(
        organization_id=org.id, user_id=u.id, role=OrganizationRole.admin.value
    )
    db.add(member)
    await db.flush()
    token = _token(str(u.id), str(org.id), OrganizationRole.admin.value)
    return u, token


@pytest_asyncio.fixture
async def viewer_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(
        id=uuid4(),
        email=f"viewer-{uuid4().hex[:6]}@test.com",
        hashed_password="x",
        organization_id=org.id,
    )
    db.add(u)
    member = OrganizationMember(
        organization_id=org.id, user_id=u.id, role=OrganizationRole.viewer.value
    )
    db.add(member)
    await db.flush()
    token = _token(str(u.id), str(org.id), OrganizationRole.viewer.value)
    return u, token


async def _make_session_with_messages(
    db: AsyncSession,
    org: Organization,
    user: User,
    messages: list[dict],
) -> ChatSession:
    cs = ChatSession(organization_id=org.id, user_id=user.id, title="test")
    db.add(cs)
    await db.flush()
    for m in messages:
        cm = ChatMessage(
            chat_session_id=cs.id,
            role=m.get("role", "assistant"),
            content=m.get("content", "answer text"),
            confidence_score=m.get("confidence_score"),
        )
        db.add(cm)
    await db.flush()
    return cs


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override():
        yield db

    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ── Service unit tests ─────────────────────────────────────────────────────────


class TestSummaryService:
    @pytest.mark.asyncio
    async def test_a_summary_zeros_when_no_data(self, db: AsyncSession, org: Organization) -> None:
        service = QueryAnalyticsService()
        result = await service.build_summary(db, organization_id=org.id)
        assert result.total_queries == 0
        assert result.unanswered_queries == 0
        assert result.low_confidence_queries == 0
        assert result.negative_feedback_count == 0
        assert result.unanswered_rate is None
        assert result.avg_confidence is None
        assert result.enabled is True

    @pytest.mark.asyncio
    async def test_b_summary_counts_unanswered_and_low_confidence(
        self, db: AsyncSession, org: Organization, admin_user: tuple[User, str]
    ) -> None:
        user, _ = admin_user
        await _make_session_with_messages(
            db,
            org,
            user,
            [
                {"role": "user", "content": "Q1"},
                {"role": "assistant", "confidence_score": None},  # unanswered
                {"role": "user", "content": "Q2"},
                {"role": "assistant", "confidence_score": 0.3},  # low confidence
                {"role": "user", "content": "Q3"},
                {"role": "assistant", "confidence_score": 0.9},  # good
            ],
        )
        service = QueryAnalyticsService()
        result = await service.build_summary(db, organization_id=org.id)
        assert result.total_queries == 3
        assert result.unanswered_queries == 1
        assert result.low_confidence_queries == 1
        assert result.answered_queries == 2

    @pytest.mark.asyncio
    async def test_c_summary_computes_negative_feedback_rate(
        self, db: AsyncSession, org: Organization, admin_user: tuple[User, str]
    ) -> None:
        user, _ = admin_user
        cs = await _make_session_with_messages(
            db,
            org,
            user,
            [{"role": "assistant", "confidence_score": 0.8}],
        )
        msg_result = await db.execute(
            __import__("sqlalchemy", fromlist=["select"])
            .select(ChatMessage)
            .where(ChatMessage.chat_session_id == cs.id)
        )
        msg = msg_result.scalar_one()
        fb = MessageFeedback(
            message_id=msg.id,
            user_id=user.id,
            organization_id=org.id,
            rating="down",
            category="missing_document",
        )
        db.add(fb)
        await db.flush()
        service = QueryAnalyticsService()
        result = await service.build_summary(db, organization_id=org.id)
        assert result.negative_feedback_count == 1
        assert result.negative_feedback_rate == 1.0
        assert any(c.category == "missing_document" for c in result.top_feedback_categories)

    @pytest.mark.asyncio
    async def test_d_summary_disabled_when_flag_off(
        self, db: AsyncSession, org: Organization
    ) -> None:
        original = settings.feature_enable_query_analytics
        settings.feature_enable_query_analytics = False
        try:
            service = QueryAnalyticsService()
            result = await service.build_summary(db, organization_id=org.id)
            assert result.enabled is False
            assert result.disabled_reason == "disabled_by_environment"
        finally:
            settings.feature_enable_query_analytics = original

    @pytest.mark.asyncio
    async def test_e_trends_returns_one_point_per_day(
        self, db: AsyncSession, org: Organization
    ) -> None:
        service = QueryAnalyticsService()
        from_date = date.today() - timedelta(days=6)
        to_date = date.today()
        result = await service.build_trends(
            db, organization_id=org.id, from_date=from_date, to_date=to_date
        )
        assert len(result.points) == 7
        assert result.points[0].date == from_date
        assert result.points[-1].date == to_date


class TestGapService:
    @pytest.mark.asyncio
    async def test_f_create_gap_redacts_example_when_policy_on(
        self, db: AsyncSession, org: Organization
    ) -> None:
        original = settings.query_analytics_redact_query_text
        settings.query_analytics_redact_query_text = True
        try:
            service = QueryAnalyticsService()
            gap = await service.create_gap(
                db,
                organization_id=org.id,
                gap_type="no_answer",
                topic_label="Redaction test",
                example_query="sensitive user query",
            )
            await db.flush()
            assert gap.example_query == "[redacted]"
        finally:
            settings.query_analytics_redact_query_text = original

    @pytest.mark.asyncio
    async def test_g_detect_gaps_creates_low_confidence_gap(
        self, db: AsyncSession, org: Organization, admin_user: tuple[User, str]
    ) -> None:
        user, _ = admin_user
        await _make_session_with_messages(
            db,
            org,
            user,
            [{"role": "assistant", "confidence_score": 0.2}] * 5,
        )
        service = QueryAnalyticsService()
        result = await service.detect_gaps(db, organization_id=org.id, min_occurrences=3)
        await db.flush()
        assert result.created >= 1
        gaps_result = await service.list_gaps(db, organization_id=org.id)
        gap_types = [g.gap_type for g in gaps_result.items]
        assert "low_confidence" in gap_types

    @pytest.mark.asyncio
    async def test_h_detect_gaps_skips_duplicate_topic(
        self, db: AsyncSession, org: Organization, admin_user: tuple[User, str]
    ) -> None:
        user, _ = admin_user
        await _make_session_with_messages(
            db,
            org,
            user,
            [{"role": "assistant", "confidence_score": 0.1}] * 5,
        )
        service = QueryAnalyticsService()
        # First detection creates the gap
        await service.detect_gaps(db, organization_id=org.id, min_occurrences=3)
        await db.flush()
        # Second detection should skip duplicates
        r2 = await service.detect_gaps(db, organization_id=org.id, min_occurrences=3)
        await db.flush()
        assert r2.skipped_duplicates >= 1
        assert r2.created == 0

    @pytest.mark.asyncio
    async def test_i_convert_gap_sets_converted_to(
        self, db: AsyncSession, org: Organization
    ) -> None:
        service = QueryAnalyticsService()
        gap = await service.create_gap(
            db,
            organization_id=org.id,
            gap_type="bad_feedback",
            topic_label="Test gap for conversion",
        )
        await db.flush()
        result = await service.convert_gap(
            db,
            organization_id=org.id,
            gap_id=__import__("uuid", fromlist=["UUID"]).UUID(gap.gap_id),
            target="eval_case",
        )
        assert result is not None
        assert result.converted_to == "eval_case"
        # Check status updated
        updated = await service.list_gaps(db, organization_id=org.id)
        gap_record = next(g for g in updated.items if g.gap_id == gap.gap_id)
        assert gap_record.status == "in_review"
        assert gap_record.converted_to == "eval_case"


# ── HTTP endpoint tests ────────────────────────────────────────────────────────


class TestQueryAnalyticsHTTP:
    @pytest.mark.asyncio
    async def test_j_summary_requires_admin(
        self, client: AsyncClient, org: Organization, viewer_user: tuple[User, str]
    ) -> None:
        _, token = viewer_user
        resp = await client.get(
            "/admin/query-analytics/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_k_summary_returns_200_for_admin(
        self, client: AsyncClient, admin_user: tuple[User, str]
    ) -> None:
        _, token = admin_user
        resp = await client.get(
            "/admin/query-analytics/summary",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_queries" in data
        assert "unanswered_rate" in data
        assert "top_feedback_categories" in data
        assert data["enabled"] is True

    @pytest.mark.asyncio
    async def test_l_gaps_list_returns_paginated(
        self, client: AsyncClient, db: AsyncSession, org: Organization, admin_user: tuple[User, str]
    ) -> None:
        _, token = admin_user
        # Create two gaps
        service = QueryAnalyticsService()
        await service.create_gap(
            db, organization_id=org.id, gap_type="no_answer", topic_label="Gap A"
        )
        await service.create_gap(
            db, organization_id=org.id, gap_type="low_confidence", topic_label="Gap B"
        )
        await db.flush()

        resp = await client.get(
            "/admin/query-analytics/gaps",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 10, "offset": 0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert isinstance(data["items"], list)

    @pytest.mark.asyncio
    async def test_m_create_gap_via_http(
        self, client: AsyncClient, admin_user: tuple[User, str]
    ) -> None:
        _, token = admin_user
        resp = await client.post(
            "/admin/query-analytics/gaps",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "gap_type": "missing_source",
                "topic_label": "HR policy documents missing",
                "description": "Users asking about leave policy get no answer",
                "occurrence_count": 12,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["topic_label"] == "HR policy documents missing"
        assert data["gap_type"] == "missing_source"
        assert data["status"] == "open"
        assert data["occurrence_count"] == 12

    @pytest.mark.asyncio
    async def test_n_patch_gap_updates_status(
        self, client: AsyncClient, db: AsyncSession, org: Organization, admin_user: tuple[User, str]
    ) -> None:
        _, token = admin_user
        service = QueryAnalyticsService()
        gap = await service.create_gap(
            db, organization_id=org.id, gap_type="bad_feedback", topic_label="Status test gap"
        )
        await db.flush()

        resp = await client.patch(
            f"/admin/query-analytics/gaps/{gap.gap_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"status": "in_review", "reviewer_notes": "Being investigated"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "in_review"
        assert data["reviewer_notes"] == "Being investigated"

    @pytest.mark.asyncio
    async def test_o_convert_gap_returns_conversion_info(
        self, client: AsyncClient, db: AsyncSession, org: Organization, admin_user: tuple[User, str]
    ) -> None:
        _, token = admin_user
        service = QueryAnalyticsService()
        gap = await service.create_gap(
            db, organization_id=org.id, gap_type="no_answer", topic_label="Convert test gap"
        )
        await db.flush()

        resp = await client.post(
            f"/admin/query-analytics/gaps/{gap.gap_id}/convert",
            headers={"Authorization": f"Bearer {token}"},
            json={"target": "review_task", "notes": "Needs reviewer attention"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["converted_to"] == "review_task"
        assert data["gap_id"] == gap.gap_id
        assert data["converted_at"] is not None

    @pytest.mark.asyncio
    async def test_tenant_isolation_gaps(
        self,
        client: AsyncClient,
        db: AsyncSession,
        org: Organization,
        other_org: Organization,
        admin_user: tuple[User, str],
    ) -> None:
        """Gaps from other_org must not appear in org's list."""
        _, token = admin_user
        service = QueryAnalyticsService()
        # Create gap in other_org
        await service.create_gap(
            db, organization_id=other_org.id, gap_type="no_answer", topic_label="Other org gap"
        )
        # Create gap in main org
        await service.create_gap(
            db, organization_id=org.id, gap_type="no_answer", topic_label="Main org gap"
        )
        await db.flush()

        resp = await client.get(
            "/admin/query-analytics/gaps",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        labels = [g["topic_label"] for g in data["items"]]
        assert "Main org gap" in labels
        assert "Other org gap" not in labels

    @pytest.mark.asyncio
    async def test_trends_endpoint_returns_daily_points(
        self, client: AsyncClient, admin_user: tuple[User, str]
    ) -> None:
        _, token = admin_user
        from_date = (date.today() - timedelta(days=6)).isoformat()
        to_date = date.today().isoformat()
        resp = await client.get(
            "/admin/query-analytics/trends",
            headers={"Authorization": f"Bearer {token}"},
            params={"from": from_date, "to": to_date},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["points"]) == 7
        for pt in data["points"]:
            assert "date" in pt
            assert "total_queries" in pt
            assert "unanswered" in pt
            assert "avg_confidence" in pt

    @pytest.mark.asyncio
    async def test_export_csv_returns_text(
        self, client: AsyncClient, admin_user: tuple[User, str]
    ) -> None:
        _, token = admin_user
        resp = await client.get(
            "/admin/query-analytics/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "date" in resp.text
        assert "total_queries" in resp.text
