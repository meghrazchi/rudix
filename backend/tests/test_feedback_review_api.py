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
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_chat_repo = ChatRepository()
_feedback_repo = FeedbackRepository()
_review_repo = FeedbackReviewRepository()


@pytest_asyncio.fixture
async def review_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _seed_admin(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, Organization]:
    org = Organization(name="Review Org", slug=f"review-org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"review-user-{uuid4().hex[:8]}",
        email=f"review-{uuid4().hex[:8]}@example.com",
        display_name="Review Admin",
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


async def _seed_feedback(
    db_session: AsyncSession,
    *,
    org: Organization,
    user: User,
    rating: str = "down",
    reason: str = "wrong_citation",
):
    chat_session = await _chat_repo.create_chat_session(
        db_session, organization_id=org.id, user_id=user.id, title="Test session"
    )
    msg = await _chat_repo.create_chat_message(
        db_session, chat_session_id=chat_session.id, role="assistant", content="Answer text here."
    )
    feedback = await _feedback_repo.upsert_feedback(
        db_session,
        message_id=msg.id,
        user_id=user.id,
        organization_id=org.id,
        rating=rating,
        reason=reason,
        comment="This is incorrect.",
    )
    await db_session.commit()
    return feedback, msg


@pytest.mark.asyncio
async def test_triage_feedback_creates_review_item(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"severity": "high", "reviewer_notes": "Needs urgent fix."},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "triaged"
    assert payload["severity"] == "high"
    assert payload["reviewer_notes"] == "Needs urgent fix."
    assert payload["feedback_id"] == str(feedback.id)


@pytest.mark.asyncio
async def test_triage_feedback_idempotent(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    headers = _headers(token=token, organization_id=str(org.id))
    r1 = await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=headers,
        json={"severity": "medium"},
    )
    r2 = await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=headers,
        json={"severity": "high"},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["review_id"] == r2.json()["review_id"]


@pytest.mark.asyncio
async def test_triage_requires_admin_role(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session, role=OrganizationRole.member)
    feedback, _msg = await _seed_feedback(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"severity": "medium"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_triage_unknown_feedback_returns_404(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await review_client.post(
        f"/api/v1/feedback-review/feedback/{uuid4()}/triage",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"severity": "low"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_review_items_empty(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await review_client.get(
        "/api/v1/feedback-review",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["total"] == 0


@pytest.mark.asyncio
async def test_list_review_items_with_filter(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    headers = _headers(token=token, organization_id=str(org.id))

    await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=headers,
        json={"severity": "high"},
    )

    r_all = await review_client.get("/api/v1/feedback-review", headers=headers)
    assert r_all.status_code == 200
    assert r_all.json()["total"] == 1

    r_filtered = await review_client.get("/api/v1/feedback-review?status=triaged", headers=headers)
    assert r_filtered.status_code == 200
    assert r_filtered.json()["total"] == 1

    r_none = await review_client.get("/api/v1/feedback-review?status=fixed", headers=headers)
    assert r_none.status_code == 200
    assert r_none.json()["total"] == 0


@pytest.mark.asyncio
async def test_update_review_status_transition(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    headers = _headers(token=token, organization_id=str(org.id))

    triage_resp = await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=headers,
        json={"severity": "medium"},
    )
    review_id = triage_resp.json()["review_id"]

    update_resp = await review_client.patch(
        f"/api/v1/feedback-review/{review_id}",
        headers=headers,
        json={"status": "fixed", "reviewer_notes": "Uploaded corrected document."},
    )
    assert update_resp.status_code == 200
    payload = update_resp.json()
    assert payload["status"] == "fixed"
    assert payload["reviewer_notes"] == "Uploaded corrected document."
    assert payload["resolved_at"] is not None


@pytest.mark.asyncio
async def test_update_review_fixed_to_open_clears_resolved_at(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    headers = _headers(token=token, organization_id=str(org.id))

    triage = await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=headers,
        json={"severity": "medium"},
    )
    review_id = triage.json()["review_id"]

    await review_client.patch(
        f"/api/v1/feedback-review/{review_id}",
        headers=headers,
        json={"status": "fixed"},
    )

    reopen_resp = await review_client.patch(
        f"/api/v1/feedback-review/{review_id}",
        headers=headers,
        json={"status": "triaged"},
    )
    assert reopen_resp.status_code == 200
    assert reopen_resp.json()["resolved_at"] is None


@pytest.mark.asyncio
async def test_get_review_item_detail(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    headers = _headers(token=token, organization_id=str(org.id))

    triage = await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=headers,
        json={"severity": "low"},
    )
    review_id = triage.json()["review_id"]

    detail_resp = await review_client.get(f"/api/v1/feedback-review/{review_id}", headers=headers)
    assert detail_resp.status_code == 200
    payload = detail_resp.json()
    assert payload["review_id"] == review_id
    assert payload["feedback"] is not None
    assert payload["feedback"]["rating"] == "down"
    assert payload["message"] is not None
    assert "Answer text" in payload["message"]["content_preview"]


@pytest.mark.asyncio
async def test_get_review_item_not_found(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await review_client.get(
        f"/api/v1/feedback-review/{uuid4()}",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_requires_admin_role(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    response = await review_client.get(
        "/api/v1/feedback-review",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_export_csv_returns_csv(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback(db_session, org=org, user=user)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    headers = _headers(token=token, organization_id=str(org.id))

    await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=headers,
        json={"severity": "medium"},
    )

    export_resp = await review_client.get("/api/v1/feedback-review/export", headers=headers)
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers["content-type"]
    csv_text = export_resp.text
    assert "review_id" in csv_text
    assert "status" in csv_text
    assert "triaged" in csv_text


@pytest.mark.asyncio
async def test_cross_org_isolation(
    review_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user_a, org_a = await _seed_admin(db_session)
    user_b, org_b = await _seed_admin(db_session)
    feedback_a, _msg_a = await _seed_feedback(db_session, org=org_a, user=user_a)

    token_a = create_app_access_token(
        subject=user_a.external_auth_id,
        organization_id=str(org_a.id),
        expires_in_seconds=600,
    )
    headers_a = _headers(token=token_a, organization_id=str(org_a.id))

    await review_client.post(
        f"/api/v1/feedback-review/feedback/{feedback_a.id}/triage",
        headers=headers_a,
        json={"severity": "high"},
    )

    token_b = create_app_access_token(
        subject=user_b.external_auth_id,
        organization_id=str(org_b.id),
        expires_in_seconds=600,
    )
    r_b = await review_client.get(
        "/api/v1/feedback-review",
        headers=_headers(token=token_b, organization_id=str(org_b.id)),
    )
    assert r_b.status_code == 200
    assert r_b.json()["total"] == 0
