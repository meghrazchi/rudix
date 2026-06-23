"""Tests for F316: Accuracy feedback capture from trust panel into evaluation datasets."""

import os
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
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.chat.repositories.feedback import FeedbackRepository
from app.domains.feedback_review.repositories.review import FeedbackReviewRepository
from app.main import app
from app.models.enums import FeedbackCategory, FeedbackReviewStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_chat_repo = ChatRepository()
_feedback_repo = FeedbackRepository()
_review_repo = FeedbackReviewRepository()


@pytest_asyncio.fixture
async def f316_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_admin(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, Organization]:
    org = Organization(name="F316 Org", slug=f"f316-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"f316-user-{uuid4().hex[:8]}",
        email=f"f316-{uuid4().hex[:8]}@example.com",
        display_name="F316 Admin",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


async def _seed_message(
    db_session: AsyncSession, *, org: Organization, user: User, content: str = "Test answer."
):
    session = await _chat_repo.create_chat_session(
        db_session, organization_id=org.id, user_id=user.id, title="F316 Session"
    )
    msg = await _chat_repo.create_chat_message(
        db_session,
        chat_session_id=session.id,
        role="assistant",
        content=content,
    )
    await db_session.commit()
    return msg


# ---------------------------------------------------------------------------
# New FeedbackCategory enum values
# ---------------------------------------------------------------------------


def test_new_category_enum_values() -> None:
    assert FeedbackCategory.missing_citation == "missing_citation"
    assert FeedbackCategory.stale_source == "stale_source"
    assert FeedbackCategory.conflicting_source == "conflicting_source"
    assert FeedbackCategory.not_enough_detail == "not_enough_detail"
    assert FeedbackCategory.should_have_said_not_found == "should_have_said_not_found"


def test_accepted_review_status_enum() -> None:
    assert FeedbackReviewStatus.accepted == "accepted"


# ---------------------------------------------------------------------------
# Feedback submission with new F316 categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_feedback_missing_citation(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    msg = await _seed_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await f316_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "down", "category": "missing_citation"},
    )

    assert response.status_code == 200
    assert response.json()["category"] == "missing_citation"


@pytest.mark.asyncio
async def test_submit_feedback_stale_source(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    msg = await _seed_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await f316_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "down", "category": "stale_source"},
    )

    assert response.status_code == 200
    assert response.json()["category"] == "stale_source"


@pytest.mark.asyncio
async def test_submit_feedback_conflicting_source(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    msg = await _seed_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await f316_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "down", "category": "conflicting_source"},
    )

    assert response.status_code == 200
    assert response.json()["category"] == "conflicting_source"


@pytest.mark.asyncio
async def test_submit_feedback_should_have_said_not_found(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    msg = await _seed_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await f316_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "down", "category": "should_have_said_not_found"},
    )

    assert response.status_code == 200
    assert response.json()["category"] == "should_have_said_not_found"


# ---------------------------------------------------------------------------
# Trust metadata, trace_id, selected_citation_ids capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_feedback_with_trust_metadata_and_trace_id(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    msg = await _seed_message(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    doc_id = str(uuid4())
    trace_id = f"trace-{uuid4().hex[:16]}"

    response = await f316_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "rating": "down",
            "category": "stale_source",
            "diagnostics": {
                "question_text": "What is the refund policy?",
                "answer_text": "Refunds within 30 days.",
                "model_name": "gpt-4o",
                "trace_id": trace_id,
                "trust_metadata": {
                    "confidence": {"score": 0.45, "trust_level": "low"},
                    "freshness": {"warning": True},
                },
                "selected_citation_ids": [doc_id],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["trace_id"] == trace_id
    assert body["selected_citation_ids"] == [doc_id]


@pytest.mark.asyncio
async def test_trust_metadata_persisted_in_db(
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    session = await _chat_repo.create_chat_session(
        db_session, organization_id=org.id, user_id=user.id, title="T"
    )
    msg = await _chat_repo.create_chat_message(
        db_session, chat_session_id=session.id, role="assistant", content="answer"
    )
    trace_id = f"t-{uuid4().hex}"
    doc_id = str(uuid4())

    feedback = await _feedback_repo.upsert_feedback(
        db_session,
        message_id=msg.id,
        user_id=user.id,
        organization_id=org.id,
        rating="down",
        reason=None,
        comment=None,
        category="stale_source",
        trust_metadata_json={"score": 0.3, "trust_level": "low"},
        trace_id=trace_id,
        selected_citation_ids=[doc_id],
    )
    await db_session.commit()

    assert feedback.trust_metadata_json == {"score": 0.3, "trust_level": "low"}
    assert feedback.trace_id == trace_id
    assert feedback.selected_citation_ids == [doc_id]


@pytest.mark.asyncio
async def test_redact_clears_trust_metadata_and_citation_ids(
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    session = await _chat_repo.create_chat_session(
        db_session, organization_id=org.id, user_id=user.id, title="T"
    )
    msg = await _chat_repo.create_chat_message(
        db_session, chat_session_id=session.id, role="assistant", content="answer"
    )

    feedback = await _feedback_repo.upsert_feedback(
        db_session,
        message_id=msg.id,
        user_id=user.id,
        organization_id=org.id,
        rating="down",
        reason=None,
        comment="sensitive info",
        category="stale_source",
        question_text="some question",
        answer_text="some answer",
        trust_metadata_json={"score": 0.3},
        selected_citation_ids=[str(uuid4())],
    )
    await db_session.commit()
    assert feedback.trust_metadata_json is not None

    redacted = await _feedback_repo.redact_feedback(
        db_session,
        feedback_id=feedback.id,
        organization_id=org.id,
    )
    await db_session.commit()

    assert redacted is not None
    assert redacted.trust_metadata_json is None
    assert redacted.selected_citation_ids is None
    assert redacted.question_text is None
    assert redacted.answer_text is None
    assert redacted.comment is None
    assert redacted.redacted_at is not None


# ---------------------------------------------------------------------------
# Accepted review status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_item_can_be_set_to_accepted(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    msg = await _seed_message(db_session, org=org, user=user)

    feedback = await _feedback_repo.upsert_feedback(
        db_session,
        message_id=msg.id,
        user_id=user.id,
        organization_id=org.id,
        rating="down",
        reason=None,
        comment=None,
        category="conflicting_source",
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    # Triage to create the review item
    triage_resp = await f316_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"severity": "high"},
    )
    assert triage_resp.status_code == 201
    review_id = triage_resp.json()["review_id"]

    # Move to accepted
    patch_resp = await f316_client.patch(
        f"/api/v1/feedback-review/{review_id}",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"status": "accepted"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "accepted"
    # accepted is not terminal — resolved_at should be null
    assert patch_resp.json()["resolved_at"] is None


# ---------------------------------------------------------------------------
# Feedback metrics endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feedback_metrics_returns_category_breakdown(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    # Seed two feedback items
    for category in ("missing_citation", "stale_source"):
        msg = await _seed_message(db_session, org=org, user=user)
        await _feedback_repo.upsert_feedback(
            db_session,
            message_id=msg.id,
            user_id=user.id,
            organization_id=org.id,
            rating="down",
            reason=None,
            comment=None,
            category=category,
        )
    await db_session.commit()

    response = await f316_client.get(
        "/api/v1/feedback-review/metrics",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_feedback"] >= 2
    categories = {c["category"] for c in body["categories"]}
    assert "missing_citation" in categories
    assert "stale_source" in categories
    assert "period_days" in body


@pytest.mark.asyncio
async def test_feedback_metrics_respects_org_isolation(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user_a, org_a = await _seed_admin(db_session)
    user_b, org_b = await _seed_admin(db_session)

    msg_a = await _seed_message(db_session, org=org_a, user=user_a)
    await _feedback_repo.upsert_feedback(
        db_session,
        message_id=msg_a.id,
        user_id=user_a.id,
        organization_id=org_a.id,
        rating="down",
        reason=None,
        comment=None,
        category="conflicting_source",
    )
    await db_session.commit()

    token_b = create_app_access_token(
        subject=user_b.external_auth_id,
        organization_id=str(org_b.id),
        expires_in_seconds=600,
    )

    response = await f316_client.get(
        "/api/v1/feedback-review/metrics",
        headers=_headers(token=token_b, organization_id=str(org_b.id)),
    )

    assert response.status_code == 200
    body = response.json()
    categories = {c["category"] for c in body["categories"]}
    # org_b has no feedback — org_a's conflicting_source must not appear
    assert "conflicting_source" not in categories


@pytest.mark.asyncio
async def test_feedback_metrics_period_days_param(
    f316_client: AsyncClient, db_session: AsyncSession
) -> None:
    user, org = await _seed_admin(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await f316_client.get(
        "/api/v1/feedback-review/metrics?days=7",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    assert response.json()["period_days"] == 7
