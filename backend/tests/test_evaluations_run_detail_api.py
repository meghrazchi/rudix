import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure strict settings can be loaded when importing modules in tests.
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
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.main import app
from app.models.enums import EvaluationRunStatus, OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def evaluations_run_detail_client(
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


async def _seed_user_and_org(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    slug_prefix: str,
) -> tuple[User, Organization]:
    organization = Organization(name=f"{slug_prefix}-org", slug=f"{slug_prefix}-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"{slug_prefix}-user-{uuid4().hex[:8]}",
        email=f"{slug_prefix}-{uuid4().hex[:8]}@example.com",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db_session.commit()
    return user, organization


def _headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


@pytest.mark.asyncio
async def test_get_evaluation_run_completed_returns_summary_and_paginated_results(
    evaluations_run_detail_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = EvaluationRepository()
    user, organization = await _seed_user_and_org(
        db_session,
        role=OrganizationRole.viewer,
        slug_prefix="eval-run-detail-completed",
    )
    evaluation_set = await repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Completed Set",
    )
    first_question = await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=evaluation_set.id,
        question="Q1",
    )
    second_question = await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=evaluation_set.id,
        question="Q2",
    )
    run = await repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.completed.value,
        config={
            "top_k": 5,
            "rerank": True,
            "metrics_summary": {
                "question_total_count": 2,
                "question_success_count": 2,
                "question_failure_count": 0,
                "retrieval_hit_rate": 1.0,
                "context_precision": 0.75,
                "context_recall": 1.0,
                "faithfulness_score": 0.8,
                "answer_relevance_score": 0.85,
                "citation_accuracy_score": 0.9,
                "refusal_accuracy": None,
                "latency_ms_total": 500,
                "latency_ms_average": 250.0,
                "cost_usd_total": 0.0005,
                "cost_usd_average": 0.00025,
                "token_input_count_total": 200,
                "token_output_count_total": 50,
                "judge_question_count": 0,
                "judge_error_count": 0,
                "comparison_targets": [
                    {
                        "label": "Baseline profile",
                        "chunking_strategy": "token_recursive",
                        "profile_version": "cfg-baseline",
                        "overall_score": 0.82,
                    },
                    {
                        "label": "Candidate profile",
                        "chunking_strategy": "paragraph_recursive",
                        "profile_version": "cfg-candidate",
                        "overall_score": 0.76,
                        "regression_failed": True,
                    },
                ],
                "comparison": {
                    "baseline_label": "Baseline profile",
                    "baseline_score": 0.82,
                    "latest_label": "Candidate profile",
                    "latest_score": 0.76,
                    "score_delta": -0.06,
                },
                "best_by_document_type": {"pdf": {"label": "Baseline profile", "score": 0.82}},
                "best_by_use_case": {"unlabeled": {"label": "Baseline profile", "score": 0.82}},
                "regressions_count": 1,
                "regression_failed": True,
            },
        },
    )
    await repository.create_evaluation_result(
        db_session,
        evaluation_run_id=run.id,
        evaluation_question_id=first_question.id,
        generated_answer="A1",
        retrieval_score=1.0,
        faithfulness_score=0.8,
        citation_accuracy_score=0.9,
        answer_relevance_score=0.85,
        latency_ms=240,
        details={"status": "completed", "metrics": {"retrieval_hit_rate": 1.0}},
    )
    await repository.create_evaluation_result(
        db_session,
        evaluation_run_id=run.id,
        evaluation_question_id=second_question.id,
        generated_answer="A2",
        retrieval_score=0.5,
        faithfulness_score=0.7,
        citation_accuracy_score=0.8,
        answer_relevance_score=0.9,
        latency_ms=260,
        details={"status": "completed", "metrics": {"retrieval_hit_rate": 0.0}},
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await evaluations_run_detail_client.get(
        f"/api/v1/evaluations/runs/{run.id}",
        headers=_headers(token=token, organization_id=str(organization.id)),
        params={"limit": 1, "offset": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["evaluation_run_id"] == str(run.id)
    assert payload["evaluation_set_id"] == str(evaluation_set.id)
    assert payload["status"] == EvaluationRunStatus.completed.value
    assert payload["summary"]["retrieval_hit_rate"] == 1.0
    assert payload["summary"]["comparison_targets"][1]["label"] == "Candidate profile"
    assert payload["summary"]["comparison"]["score_delta"] == -0.06
    assert payload["config"]["top_k"] == 5
    assert payload["results"]["total"] == 2
    assert payload["results"]["limit"] == 1
    assert payload["results"]["offset"] == 1
    assert len(payload["results"]["items"]) == 1
    assert payload["results"]["items"][0]["question"] in {"Q1", "Q2"}


@pytest.mark.asyncio
async def test_get_evaluation_run_returns_current_status_for_queued_and_running(
    evaluations_run_detail_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = EvaluationRepository()
    user, organization = await _seed_user_and_org(
        db_session,
        role=OrganizationRole.member,
        slug_prefix="eval-run-detail-status",
    )
    evaluation_set = await repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Status Set",
    )
    queued_run = await repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.queued.value,
        config={"top_k": 3},
    )
    running_run = await repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.running.value,
        config={"top_k": 3},
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    queued_response = await evaluations_run_detail_client.get(
        f"/api/v1/evaluations/runs/{queued_run.id}",
        headers=_headers(token=token, organization_id=str(organization.id)),
    )
    running_response = await evaluations_run_detail_client.get(
        f"/api/v1/evaluations/runs/{running_run.id}",
        headers=_headers(token=token, organization_id=str(organization.id)),
    )

    assert queued_response.status_code == 200
    assert queued_response.json()["status"] == EvaluationRunStatus.queued.value
    assert queued_response.json()["results"]["total"] == 0
    assert running_response.status_code == 200
    assert running_response.json()["status"] == EvaluationRunStatus.running.value
    assert running_response.json()["results"]["total"] == 0


@pytest.mark.asyncio
async def test_get_evaluation_run_failed_includes_safe_failure_reason(
    evaluations_run_detail_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = EvaluationRepository()
    user, organization = await _seed_user_and_org(
        db_session,
        role=OrganizationRole.admin,
        slug_prefix="eval-run-detail-failed",
    )
    evaluation_set = await repository.create_evaluation_set(
        db_session,
        organization_id=organization.id,
        name="Failed Set",
    )
    question = await repository.create_evaluation_question(
        db_session,
        evaluation_set_id=evaluation_set.id,
        question="Why failed?",
    )
    failed_run = await repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set.id,
        status=EvaluationRunStatus.failed.value,
        config={"top_k": 4},
    )
    await repository.create_evaluation_result(
        db_session,
        evaluation_run_id=failed_run.id,
        evaluation_question_id=question.id,
        generated_answer=None,
        retrieval_score=None,
        faithfulness_score=None,
        citation_accuracy_score=None,
        answer_relevance_score=None,
        latency_ms=40,
        details={
            "status": "failed",
            "error_type": "RuntimeError",
            "error": "qdrant timeout",
            "metrics": {"judge_error": "RuntimeError"},
        },
    )
    await db_session.commit()

    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )
    response = await evaluations_run_detail_client.get(
        f"/api/v1/evaluations/runs/{failed_run.id}",
        headers=_headers(token=token, organization_id=str(organization.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == EvaluationRunStatus.failed.value
    assert payload["failure_reason"] == "qdrant timeout"
    assert payload["failure_type"] == "RuntimeError"
    assert payload["results"]["items"][0]["failure_reason"] == "qdrant timeout"


@pytest.mark.asyncio
async def test_get_evaluation_run_rejects_cross_organization_access(
    evaluations_run_detail_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    repository = EvaluationRepository()
    user_a, org_a = await _seed_user_and_org(
        db_session,
        role=OrganizationRole.viewer,
        slug_prefix="eval-run-detail-a",
    )
    _user_b, org_b = await _seed_user_and_org(
        db_session,
        role=OrganizationRole.viewer,
        slug_prefix="eval-run-detail-b",
    )
    evaluation_set_b = await repository.create_evaluation_set(
        db_session,
        organization_id=org_b.id,
        name="B Set",
    )
    run_b = await repository.create_evaluation_run(
        db_session,
        evaluation_set_id=evaluation_set_b.id,
        status=EvaluationRunStatus.completed.value,
        config={"top_k": 3},
    )
    await db_session.commit()

    token_a = create_app_access_token(
        subject=user_a.external_auth_id,
        organization_id=str(org_a.id),
        expires_in_seconds=600,
    )
    response = await evaluations_run_detail_client.get(
        f"/api/v1/evaluations/runs/{run_b.id}",
        headers=_headers(token=token_a, organization_id=str(org_a.id)),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Evaluation run not found"


@pytest.mark.asyncio
async def test_get_evaluation_run_invalid_id_returns_404(
    evaluations_run_detail_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, organization = await _seed_user_and_org(
        db_session,
        role=OrganizationRole.viewer,
        slug_prefix="eval-run-detail-invalid",
    )
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(organization.id),
        expires_in_seconds=600,
    )

    response = await evaluations_run_detail_client.get(
        "/api/v1/evaluations/runs/not-a-uuid",
        headers=_headers(token=token, organization_id=str(organization.id)),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Evaluation run not found"
