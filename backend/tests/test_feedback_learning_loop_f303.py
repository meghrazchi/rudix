"""Tests for F303: Answer feedback learning loop into evaluation datasets."""

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

from datetime import UTC

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.chat.repositories.feedback import FeedbackRepository
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.feedback_review.repositories.review import FeedbackReviewRepository
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

_chat_repo = ChatRepository()
_feedback_repo = FeedbackRepository()
_review_repo = FeedbackReviewRepository()
_eval_repo = EvaluationRepository()


@pytest_asyncio.fixture
async def f303_client(
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
    org = Organization(name="F303 Org", slug=f"f303-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"f303-user-{uuid4().hex[:8]}",
        email=f"f303-{uuid4().hex[:8]}@example.com",
        display_name="F303 Admin",
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


async def _seed_feedback_with_diagnostics(
    db_session: AsyncSession,
    *,
    org: Organization,
    user: User,
    question_text: str = "What is the capital of France?",
    answer_text: str = "The capital of France is Berlin.",
    category: str = "wrong_answer",
):
    session = await _chat_repo.create_chat_session(
        db_session, organization_id=org.id, user_id=user.id, title="Test"
    )
    msg = await _chat_repo.create_chat_message(
        db_session,
        chat_session_id=session.id,
        role="assistant",
        content=answer_text,
    )
    feedback = await _feedback_repo.upsert_feedback(
        db_session,
        message_id=msg.id,
        user_id=user.id,
        organization_id=org.id,
        rating="down",
        reason="hallucination",
        comment="Wrong city.",
        category=category,
        question_text=question_text,
        answer_text=answer_text,
        citations_json={"items": [{"doc_id": str(uuid4()), "title": "France guide", "page": 1}]},
        retrieval_diagnostics_json={"retrieval_score": 0.42, "profile": "default"},
        model_name="test-model-1.0",
    )
    await db_session.commit()
    return feedback, msg


async def _seed_eval_set(
    db_session: AsyncSession,
    *,
    org: Organization,
    user: User,
    name: str = "F303 Test Dataset",
):
    evaluation_set = await _eval_repo.create_evaluation_set(
        db_session,
        organization_id=org.id,
        name=name,
        description=None,
        owner_id=user.id,
    )
    await db_session.commit()
    return evaluation_set


# ---------------------------------------------------------------------------
# Feedback submission tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_feedback_with_category_and_diagnostics(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    session = await _chat_repo.create_chat_session(
        db_session, organization_id=org.id, user_id=user.id, title="Test"
    )
    msg = await _chat_repo.create_chat_message(
        db_session, chat_session_id=session.id, role="assistant", content="Paris is the capital."
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "rating": "down",
            "category": "wrong_answer",
            "diagnostics": {
                "question_text": "What is the capital of France?",
                "answer_text": "Paris is the capital.",
                "model_name": "gpt-4o",
                "citations": [{"doc_id": str(uuid4()), "title": "Geography doc"}],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rating"] == "down"
    assert payload["category"] == "wrong_answer"
    assert payload["question_text"] == "What is the capital of France?"
    assert payload["answer_text"] == "Paris is the capital."
    assert payload["model_name"] == "gpt-4o"
    assert payload["retain_until"] is not None
    assert payload["redacted_at"] is None
    assert payload["converted_to_eval_question_id"] is None


@pytest.mark.asyncio
async def test_submit_feedback_without_diagnostics_stays_backward_compatible(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    session = await _chat_repo.create_chat_session(
        db_session, organization_id=org.id, user_id=user.id, title="Test"
    )
    msg = await _chat_repo.create_chat_message(
        db_session, chat_session_id=session.id, role="assistant", content="Some answer."
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.put(
        f"/api/v1/chat/messages/{msg.id}/feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"rating": "up"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rating"] == "up"
    assert payload["category"] is None
    assert payload["question_text"] is None


@pytest.mark.asyncio
async def test_all_feedback_categories_accepted(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    categories = [
        "wrong_answer",
        "bad_citation",
        "outdated_source",
        "missing_information",
        "low_confidence",
        "unsafe_response",
    ]

    for cat in categories:
        session = await _chat_repo.create_chat_session(
            db_session, organization_id=org.id, user_id=user.id, title="Cat test"
        )
        msg = await _chat_repo.create_chat_message(
            db_session, chat_session_id=session.id, role="assistant", content="Answer."
        )
        await db_session.commit()

        token = create_app_access_token(
            subject=user.external_auth_id,
            organization_id=str(org.id),
            expires_in_seconds=600,
        )
        response = await f303_client.put(
            f"/api/v1/chat/messages/{msg.id}/feedback",
            headers=_headers(token=token, organization_id=str(org.id)),
            json={"rating": "down", "category": cat},
        )
        assert response.status_code == 200, f"Failed for category: {cat}"
        assert response.json()["category"] == cat


# ---------------------------------------------------------------------------
# Convert-to-eval endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_convert_review_to_eval_case_creates_question(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback_with_diagnostics(db_session, org=org, user=user)
    eval_set = await _seed_eval_set(db_session, org=org, user=user)

    # First triage the feedback to create a review item
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    triage_resp = await f303_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"severity": "high"},
    )
    assert triage_resp.status_code == 201
    review_id = triage_resp.json()["review_id"]

    # Convert to eval case
    convert_resp = await f303_client.post(
        f"/api/v1/feedback-review/{review_id}/convert-to-eval",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "evaluation_set_id": str(eval_set.id),
            "default_difficulty": "hard",
            "reviewer_notes": "Critical regression case.",
        },
    )

    assert convert_resp.status_code == 201
    payload = convert_resp.json()
    assert payload["review_id"] == review_id
    assert payload["evaluation_set_id"] == str(eval_set.id)
    assert payload["question"] == "What is the capital of France?"
    assert payload["already_existed"] is False
    assert payload["evaluation_question_id"]


@pytest.mark.asyncio
async def test_convert_review_sets_status_to_eval_created(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback_with_diagnostics(db_session, org=org, user=user)
    eval_set = await _seed_eval_set(db_session, org=org, user=user)

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    triage_resp = await f303_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/triage",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"severity": "medium"},
    )
    review_id = triage_resp.json()["review_id"]

    await f303_client.post(
        f"/api/v1/feedback-review/{review_id}/convert-to-eval",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"evaluation_set_id": str(eval_set.id)},
    )

    # Verify the review item status was updated
    get_resp = await f303_client.get(
        f"/api/v1/feedback-review/{review_id}",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert get_resp.status_code == 200
    item = get_resp.json()
    assert item["status"] == "eval_created"
    assert item["linked_eval_question_id"] is not None
    assert item["resolved_at"] is not None


@pytest.mark.asyncio
async def test_convert_review_skips_duplicate_question(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    eval_set = await _seed_eval_set(db_session, org=org, user=user)

    # Seed two feedbacks with identical question_text
    question = "What is the capital of France?"
    feedback1, _ = await _seed_feedback_with_diagnostics(
        db_session, org=org, user=user, question_text=question
    )
    feedback2, _ = await _seed_feedback_with_diagnostics(
        db_session, org=org, user=user, question_text=question
    )

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )

    async def _triage_and_convert(feedback_id: str) -> dict:
        tr = await f303_client.post(
            f"/api/v1/feedback-review/feedback/{feedback_id}/triage",
            headers=_headers(token=token, organization_id=str(org.id)),
            json={"severity": "low"},
        )
        review_id = tr.json()["review_id"]
        cr = await f303_client.post(
            f"/api/v1/feedback-review/{review_id}/convert-to-eval",
            headers=_headers(token=token, organization_id=str(org.id)),
            json={"evaluation_set_id": str(eval_set.id)},
        )
        return cr.json()

    r1 = await _triage_and_convert(str(feedback1.id))
    r2 = await _triage_and_convert(str(feedback2.id))

    assert r1["already_existed"] is False
    assert r2["already_existed"] is True
    assert r1["evaluation_question_id"] == r2["evaluation_question_id"]


@pytest.mark.asyncio
async def test_convert_review_not_found_returns_404(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    eval_set = await _seed_eval_set(db_session, org=org, user=user)

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.post(
        f"/api/v1/feedback-review/{uuid4()}/convert-to-eval",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"evaluation_set_id": str(eval_set.id)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_convert_review_requires_admin_role(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    member, org = await _seed_admin(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=member.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.post(
        f"/api/v1/feedback-review/{uuid4()}/convert-to-eval",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={"evaluation_set_id": str(uuid4())},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Redaction tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redact_feedback_clears_diagnostic_fields(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback_with_diagnostics(db_session, org=org, user=user)

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.post(
        f"/api/v1/feedback-review/feedback/{feedback.id}/redact",
        headers=_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    fb = payload.get("feedback") or payload
    # The feedback summary in the response should show redacted_at set
    assert (
        fb.get("redacted_at") is not None
        or payload.get("feedback", {}).get("redacted_at") is not None
    )

    # Verify DB directly
    await db_session.refresh(feedback)
    assert feedback.redacted_at is not None
    assert feedback.question_text is None
    assert feedback.answer_text is None
    assert feedback.citations_json is None
    assert feedback.retrieval_diagnostics_json is None
    assert feedback.comment is None


@pytest.mark.asyncio
async def test_redact_feedback_not_found_returns_404(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.post(
        f"/api/v1/feedback-review/feedback/{uuid4()}/redact",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_redact_requires_admin_role(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    member, org = await _seed_admin(db_session, role=OrganizationRole.member)
    token = create_app_access_token(
        subject=member.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.post(
        f"/api/v1/feedback-review/feedback/{uuid4()}/redact",
        headers=_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# from-feedback evaluation set tests (enhanced)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_from_feedback_uses_question_text_for_eval_case(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    question = "Who wrote Hamlet?"
    answer = "Shakespeare wrote Hamlet."
    feedback, _msg = await _seed_feedback_with_diagnostics(
        db_session, org=org, user=user, question_text=question, answer_text=answer
    )
    eval_set = await _seed_eval_set(db_session, org=org, user=user)

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.post(
        "/api/v1/evaluation-sets/from-feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "evaluation_set_id": str(eval_set.id),
            "feedback_ids": [str(feedback.id)],
            "default_difficulty": "medium",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["created"] == 1
    assert payload["skipped"] == 0

    # Verify the eval question uses question_text as question
    from sqlalchemy import select

    from app.models.evaluation import EvaluationQuestion

    result = await db_session.execute(
        select(EvaluationQuestion).where(EvaluationQuestion.evaluation_set_id == eval_set.id)
    )
    questions = result.scalars().all()
    assert len(questions) == 1
    assert questions[0].question == question
    assert questions[0].expected_answer == answer


@pytest.mark.asyncio
async def test_from_feedback_marks_feedback_as_converted(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback_with_diagnostics(db_session, org=org, user=user)
    eval_set = await _seed_eval_set(db_session, org=org, user=user)

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    response = await f303_client.post(
        "/api/v1/evaluation-sets/from-feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "evaluation_set_id": str(eval_set.id),
            "feedback_ids": [str(feedback.id)],
        },
    )

    assert response.status_code == 201
    await db_session.refresh(feedback)
    assert feedback.converted_to_eval_question_id is not None


@pytest.mark.asyncio
async def test_from_feedback_stores_diagnostics_in_metadata(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback_with_diagnostics(
        db_session,
        org=org,
        user=user,
        category="bad_citation",
    )
    eval_set = await _seed_eval_set(db_session, org=org, user=user)

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    await f303_client.post(
        "/api/v1/evaluation-sets/from-feedback",
        headers=_headers(token=token, organization_id=str(org.id)),
        json={
            "evaluation_set_id": str(eval_set.id),
            "feedback_ids": [str(feedback.id)],
        },
    )

    from sqlalchemy import select

    from app.models.evaluation import EvaluationQuestion

    result = await db_session.execute(
        select(EvaluationQuestion).where(EvaluationQuestion.evaluation_set_id == eval_set.id)
    )
    question = result.scalars().first()
    assert question is not None
    meta = question.metadata_json or {}
    assert meta.get("category") == "bad_citation"
    assert meta.get("source") == "feedback"
    assert meta.get("model_name") == "test-model-1.0"
    assert "citations" in meta


@pytest.mark.asyncio
async def test_from_feedback_org_isolation(
    f303_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Feedback from org A must not be visible to org B."""
    user_a, org_a = await _seed_admin(db_session)
    user_b, org_b = await _seed_admin(db_session)

    feedback_a, _msg = await _seed_feedback_with_diagnostics(db_session, org=org_a, user=user_a)
    eval_set_b = await _seed_eval_set(db_session, org=org_b, user=user_b)

    token_b = create_app_access_token(
        subject=user_b.external_auth_id,
        organization_id=str(org_b.id),
        expires_in_seconds=600,
    )
    response = await f303_client.post(
        "/api/v1/evaluation-sets/from-feedback",
        headers=_headers(token=token_b, organization_id=str(org_b.id)),
        json={
            "evaluation_set_id": str(eval_set_b.id),
            "feedback_ids": [str(feedback_a.id)],
        },
    )
    assert response.status_code == 201
    payload = response.json()
    # feedback_a belongs to org_a so should be skipped for org_b
    assert payload["skipped"] == 1
    assert payload["created"] == 0


# ---------------------------------------------------------------------------
# Retention tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feedback_sets_retain_until_on_creation(
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_admin(db_session)
    feedback, _msg = await _seed_feedback_with_diagnostics(db_session, org=org, user=user)
    assert feedback.retain_until is not None
    # Should be ~90 days from now
    from datetime import datetime

    diff = (feedback.retain_until - datetime.now(tz=UTC)).days
    assert 88 <= diff <= 91
