"""Backend tests for F353: Usage & Adoption report.

Covers:
  A. UsageAdoptionService.get_summary — active/new/returning users
  B. UsageAdoptionService.get_summary — questions, documents, citation clicks, trust panel opens
  C. UsageAdoptionService.get_summary — feedback, saved answers, invitations
  D. UsageAdoptionService.get_summary — role filter narrows/empties results
  E. UsageAdoptionService.get_activation_funnel — cohort semantics + drop-off
  F. UsageAdoptionService.get_charts — active_users_series + role_adoption_comparison
  G. UsageAdoptionService.list_users — row shape + onboarding_status
  H. UsageAdoptionService.list_users — pagination
  I. UsageAdoptionService.build_export_csv — header + row content
  J. HTTP — GET /admin/usage-adoption/summary requires admin/owner role (member 403)
  K. HTTP — GET /admin/usage-adoption/summary org isolation
  L. HTTP — GET /admin/usage-adoption/users returns filterable rows
  M. HTTP — GET /admin/usage-adoption/export returns CSV with header row
  N. HTTP — POST .../onboarding-reminder sends when email is enabled, 404 for unknown user

Run:
    pytest tests/test_usage_adoption_f353.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
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
from app.db.session import get_db_session
from app.domains.admin.services.usage_adoption_service import (
    UsageAdoptionFilters,
    UsageAdoptionService,
)
from app.main import app
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.message_feedback import MessageFeedback
from app.models.organization import Organization
from app.models.organization_invitation import OrganizationInvitation
from app.models.organization_member import OrganizationMember
from app.models.usage import UsageEvent
from app.models.user import User
from app.models.verified_answer import VerifiedAnswer

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def usage_adoption_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "email_enabled", True)
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


async def _make_org(db: AsyncSession) -> Organization:
    slug = f"ua-org-{uuid4().hex[:8]}"
    org = Organization(name=f"Usage Adoption Org {slug}", slug=slug)
    db.add(org)
    await db.flush()
    return org


async def _make_user(
    db: AsyncSession,
    org: Organization,
    *,
    role: str = OrganizationRole.admin.value,
    email: str | None = None,
    display_name: str = "UA User",
) -> User:
    user = User(email=email or f"ua-{uuid4().hex[:6]}@test.com", display_name=display_name)
    db.add(user)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
    await db.flush()
    return user


async def _chat_session(db: AsyncSession, org: Organization, user: User) -> ChatSession:
    cs = ChatSession(organization_id=org.id, user_id=user.id, title="Session")
    db.add(cs)
    await db.flush()
    return cs


async def _ask_question(db: AsyncSession, session: ChatSession) -> ChatMessage:
    msg = ChatMessage(chat_session_id=session.id, role="user", content="What is the policy?")
    db.add(msg)
    await db.flush()
    return msg


def _usage_event(
    org: Organization,
    user: User,
    event_type: str,
    *,
    created_at: datetime,
) -> UsageEvent:
    return UsageEvent(
        organization_id=org.id, user_id=user.id, event_type=event_type, created_at=created_at
    )


# ---------------------------------------------------------------------------
# A. Summary — active/new/returning users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_active_new_returning_users(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    admin = await _make_user(db_session, org)
    now = datetime.now(tz=UTC)

    new_user = await _make_user(db_session, org, role=OrganizationRole.member.value)
    returning_user = await _make_user(db_session, org, role=OrganizationRole.member.value)

    db_session.add(_usage_event(org, new_user, "analytics.v1.feature.chat.opened", created_at=now))
    db_session.add(
        _usage_event(
            org,
            returning_user,
            "analytics.v1.feature.chat.opened",
            created_at=now - timedelta(days=45),
        )
    )
    db_session.add(
        _usage_event(
            org,
            returning_user,
            "analytics.v1.feature.chat.opened",
            created_at=now - timedelta(days=1),
        )
    )
    await db_session.commit()

    summary = await UsageAdoptionService().get_summary(
        db_session, organization_id=org.id, filters=UsageAdoptionFilters()
    )
    assert summary.active_users == 2
    assert summary.new_users == 1
    assert summary.returning_users == 1
    assert admin.id  # admin has no activity and isn't counted


# ---------------------------------------------------------------------------
# B. Summary — questions, documents, citations, trust panel opens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_questions_documents_citations(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    user = await _make_user(db_session, org)
    now = datetime.now(tz=UTC)

    session = await _chat_session(db_session, org, user)
    await _ask_question(db_session, session)
    await _ask_question(db_session, session)

    db_session.add(Document(organization_id=org.id, filename="a.pdf", uploaded_by_user_id=user.id))
    await db_session.flush()

    db_session.add(
        _usage_event(org, user, "analytics.v1.feature.chat.citation_opened", created_at=now)
    )
    db_session.add(
        _usage_event(org, user, "analytics.v1.feature.chat.trust_panel_opened", created_at=now)
    )
    await db_session.commit()

    summary = await UsageAdoptionService().get_summary(
        db_session, organization_id=org.id, filters=UsageAdoptionFilters()
    )
    assert summary.questions_asked == 2
    assert summary.documents_uploaded == 1
    assert summary.citation_clicks == 1
    assert summary.trust_panel_opens == 1


# ---------------------------------------------------------------------------
# C. Summary — feedback, saved answers, invitations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_feedback_saved_answers_invitations(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    user = await _make_user(db_session, org)
    now = datetime.now(tz=UTC)

    session = await _chat_session(db_session, org, user)
    answer = ChatMessage(chat_session_id=session.id, role="assistant", content="The answer.")
    db_session.add(answer)
    await db_session.flush()
    db_session.add(
        MessageFeedback(
            message_id=answer.id,
            user_id=user.id,
            organization_id=org.id,
            rating="up",
        )
    )
    db_session.add(
        VerifiedAnswer(
            organization_id=org.id,
            title="Card",
            question="Q?",
            answer_text="A.",
            created_by_id=user.id,
        )
    )
    db_session.add(
        OrganizationInvitation(
            organization_id=org.id,
            email="invitee@test.com",
            role=OrganizationRole.member.value,
            token_hash="hash1",
            expires_at=now + timedelta(days=7),
            invited_by_user_id=user.id,
            accepted_at=now,
        )
    )
    await db_session.commit()

    summary = await UsageAdoptionService().get_summary(
        db_session, organization_id=org.id, filters=UsageAdoptionFilters()
    )
    assert summary.feedback_submitted == 1
    assert summary.saved_answers == 1
    assert summary.invitations_sent == 1
    assert summary.invitations_accepted == 1


# ---------------------------------------------------------------------------
# D. Summary — role filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_role_filter_narrows_and_empties(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    member = await _make_user(db_session, org, role=OrganizationRole.member.value)
    now = datetime.now(tz=UTC)
    db_session.add(_usage_event(org, member, "analytics.v1.feature.chat.opened", created_at=now))
    await db_session.commit()

    service = UsageAdoptionService()
    member_summary = await service.get_summary(
        db_session,
        organization_id=org.id,
        filters=UsageAdoptionFilters(role=OrganizationRole.member.value),
    )
    assert member_summary.active_users == 1

    viewer_summary = await service.get_summary(
        db_session,
        organization_id=org.id,
        filters=UsageAdoptionFilters(role=OrganizationRole.viewer.value),
    )
    assert viewer_summary.active_users == 0
    assert viewer_summary.onboarding_completion_rate is None


# ---------------------------------------------------------------------------
# E. Activation funnel — cohort semantics + drop-off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_activation_funnel_cohort_and_drop_off(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    now = datetime.now(tz=UTC)

    activated = await _make_user(db_session, org, role=OrganizationRole.member.value)
    dropped_off = await _make_user(db_session, org, role=OrganizationRole.member.value)

    db_session.add(
        Document(organization_id=org.id, filename="doc.pdf", uploaded_by_user_id=activated.id)
    )
    db_session.add(
        Document(organization_id=org.id, filename="other.pdf", uploaded_by_user_id=dropped_off.id)
    )
    db_session.add(
        _usage_event(
            org, activated, "analytics.v1.activation.first_indexed_document", created_at=now
        )
    )
    db_session.add(
        _usage_event(org, activated, "analytics.v1.activation.first_question", created_at=now)
    )
    await db_session.commit()

    funnel = await UsageAdoptionService().get_activation_funnel(
        db_session, organization_id=org.id, filters=UsageAdoptionFilters()
    )
    steps = {step.step: step for step in funnel}
    assert steps["connected_or_uploaded_source"].users_reached == 2
    assert steps["source_indexed"].users_reached == 1
    assert steps["asked_first_question"].users_reached == 1
    # drop-off from "connected_or_uploaded_source" (2) to "source_indexed" (1) is 50%
    assert steps["source_indexed"].drop_off_rate == 0.5


@pytest.mark.asyncio
async def test_activation_funnel_excludes_users_outside_signup_cohort(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    in_range = date(2026, 6, 15)
    out_of_range = date(2026, 1, 1)

    user_in = User(email=f"in-{uuid4().hex[:6]}@test.com", display_name="In range")
    user_out = User(email=f"out-{uuid4().hex[:6]}@test.com", display_name="Out of range")
    db_session.add(user_in)
    db_session.add(user_out)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user_in.id, role="member"))
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user_out.id, role="member"))
    await db_session.flush()
    # created_at has a server_default; overwrite directly for cohort filtering.
    user_in.created_at = datetime.combine(in_range, datetime.min.time(), tzinfo=UTC)
    user_out.created_at = datetime.combine(out_of_range, datetime.min.time(), tzinfo=UTC)
    await db_session.commit()

    funnel = await UsageAdoptionService().get_activation_funnel(
        db_session,
        organization_id=org.id,
        filters=UsageAdoptionFilters(from_date=date(2026, 6, 1), to_date=date(2026, 6, 30)),
    )
    signed_up = next(step for step in funnel if step.step == "signed_up")
    assert signed_up.users_reached == 1


# ---------------------------------------------------------------------------
# F. Charts — active_users_series + role_adoption_comparison
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_charts_active_users_series_and_role_adoption(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    admin = await _make_user(db_session, org, role=OrganizationRole.admin.value)
    member = await _make_user(db_session, org, role=OrganizationRole.member.value)
    today = datetime.now(tz=UTC)

    db_session.add(_usage_event(org, admin, "analytics.v1.feature.chat.opened", created_at=today))
    session = await _chat_session(db_session, org, member)
    await _ask_question(db_session, session)
    await db_session.commit()

    charts = await UsageAdoptionService().get_charts(
        db_session, organization_id=org.id, filters=UsageAdoptionFilters()
    )
    todays_point = next(
        point for point in charts.active_users_series if point.date == today.date().isoformat()
    )
    assert todays_point.active_users == 1

    role_rows = {row.role: row for row in charts.role_adoption_comparison}
    assert role_rows["admin"].user_count == 1
    assert role_rows["member"].user_count == 1
    assert role_rows["member"].questions_asked == 1
    assert len(charts.funnel) == 9


# ---------------------------------------------------------------------------
# G. list_users — row shape + onboarding_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_onboarding_status(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    completed = await _make_user(
        db_session, org, role=OrganizationRole.member.value, display_name="Completed User"
    )
    untouched = await _make_user(
        db_session, org, role=OrganizationRole.member.value, display_name="Untouched User"
    )
    now = datetime.now(tz=UTC)

    db_session.add(
        Document(organization_id=org.id, filename="doc.pdf", uploaded_by_user_id=completed.id)
    )
    db_session.add(
        _usage_event(
            org, completed, "analytics.v1.activation.first_indexed_document", created_at=now
        )
    )
    db_session.add(
        _usage_event(org, completed, "analytics.v1.activation.first_question", created_at=now)
    )
    db_session.add(
        _usage_event(org, completed, "analytics.v1.feature.chat.citation_opened", created_at=now)
    )
    await db_session.commit()

    result = await UsageAdoptionService().list_users(
        db_session, organization_id=org.id, filters=UsageAdoptionFilters()
    )
    rows_by_name = {row.name: row for row in result.rows}
    assert rows_by_name["Completed User"].onboarding_status == "completed"
    assert rows_by_name["Untouched User"].onboarding_status == "not_started"
    assert untouched.id


# ---------------------------------------------------------------------------
# H. list_users — pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_pagination(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    for i in range(5):
        await _make_user(
            db_session, org, role=OrganizationRole.member.value, display_name=f"User {i}"
        )
    await db_session.commit()

    result = await UsageAdoptionService().list_users(
        db_session,
        organization_id=org.id,
        filters=UsageAdoptionFilters(),
        page=1,
        page_size=2,
    )
    assert result.total == 5
    assert len(result.rows) == 2
    assert result.page == 1


# ---------------------------------------------------------------------------
# I. build_export_csv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_export_csv_header_and_row(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    await _make_user(db_session, org, role=OrganizationRole.member.value, display_name="Csv User")
    await db_session.commit()

    csv_text = await UsageAdoptionService().build_export_csv(
        db_session, organization_id=org.id, filters=UsageAdoptionFilters()
    )
    lines = csv_text.strip().splitlines()
    assert lines[0] == (
        "name,email,role,last_active_at,questions_asked,sources_used,"
        "citation_clicks,feedback_submitted,saved_answers,onboarding_status"
    )
    assert any("Csv User" in line for line in lines[1:])


# ---------------------------------------------------------------------------
# J. HTTP — role guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_summary_member_gets_403(
    usage_adoption_client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await _make_org(db_session)
    member = await _make_user(db_session, org, role=OrganizationRole.member.value)
    await db_session.commit()
    token = _token(str(member.id), str(org.id), OrganizationRole.member.value)

    resp = await usage_adoption_client.get(
        "/api/admin/usage-adoption/summary", headers=_auth(token)
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# K. HTTP — org isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_summary_org_isolation(
    usage_adoption_client: AsyncClient, db_session: AsyncSession
) -> None:
    org_a = await _make_org(db_session)
    admin_a = await _make_user(db_session, org_a)
    org_b = await _make_org(db_session)
    member_b = await _make_user(db_session, org_b, role=OrganizationRole.member.value)
    now = datetime.now(tz=UTC)
    db_session.add(
        _usage_event(org_b, member_b, "analytics.v1.feature.chat.opened", created_at=now)
    )
    await db_session.commit()

    token = _token(str(admin_a.id), str(org_a.id), OrganizationRole.admin.value)
    resp = await usage_adoption_client.get(
        "/api/admin/usage-adoption/summary", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["active_users"] == 0


# ---------------------------------------------------------------------------
# L. HTTP — users list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_list_users(
    usage_adoption_client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await _make_org(db_session)
    admin = await _make_user(db_session, org, display_name="Admin Person")
    await _make_user(
        db_session, org, role=OrganizationRole.member.value, display_name="Member Person"
    )
    await db_session.commit()
    token = _token(str(admin.id), str(org.id), OrganizationRole.admin.value)

    resp = await usage_adoption_client.get(
        "/api/admin/usage-adoption/users",
        headers=_auth(token),
        params={"role": "member"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["rows"][0]["name"] == "Member Person"


# ---------------------------------------------------------------------------
# M. HTTP — CSV export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_export_csv(
    usage_adoption_client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await _make_org(db_session)
    admin = await _make_user(db_session, org, display_name="Export Person")
    await db_session.commit()
    token = _token(str(admin.id), str(org.id), OrganizationRole.admin.value)

    resp = await usage_adoption_client.get("/api/admin/usage-adoption/export", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Export Person" in resp.text


# ---------------------------------------------------------------------------
# N. HTTP — onboarding reminder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_onboarding_reminder_sent_and_404(
    usage_adoption_client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await _make_org(db_session)
    admin = await _make_user(db_session, org, display_name="Reminder Admin")
    target = await _make_user(
        db_session, org, role=OrganizationRole.member.value, display_name="Reminder Target"
    )
    await db_session.commit()
    token = _token(str(admin.id), str(org.id), OrganizationRole.admin.value)

    resp = await usage_adoption_client.post(
        f"/api/admin/usage-adoption/users/{target.id}/onboarding-reminder",
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["sent"] is True

    missing_resp = await usage_adoption_client.post(
        f"/api/admin/usage-adoption/users/{uuid4()}/onboarding-reminder",
        headers=_auth(token),
    )
    assert missing_resp.status_code == 404
