"""Backend tests for F148: Evaluation run comparison and regression analysis.

Covers: list runs, metric delta calculations, regression/improvement flags,
per-case comparison, filters (difficulty, tags, case_status, failure_type),
CSV/JSON export, org isolation, and role guards.
"""

import json
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
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.main import app
from app.models.enums import EvaluationRunStatus, OrganizationRole
from app.models.evaluation import EvaluationRun
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def comparison_client(
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


async def _seed_org_and_user(
    db_session: AsyncSession,
    *,
    role: OrganizationRole = OrganizationRole.admin,
) -> tuple[User, Organization]:
    org = Organization(name=f"Org-{uuid4().hex[:6]}", slug=f"org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"u-{uuid4().hex[:8]}",
        email=f"u-{uuid4().hex[:8]}@test.com",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


def _headers(*, token: str, org_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": org_id,
    }


def _token(user: User, org: Organization) -> str:
    return create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )


async def _seed_run_with_results(
    db_session: AsyncSession,
    *,
    org: Organization,
    repo: EvaluationRepository,
    summary: dict | None = None,
    run_name: str | None = None,
    status: str = EvaluationRunStatus.completed.value,
    results: list[dict] | None = None,
) -> tuple[EvaluationRun, list]:
    """Create an evaluation set + run + questions + results for testing."""
    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name=f"Set-{uuid4().hex[:6]}"
    )

    config: dict = {}
    if summary:
        config["metrics_summary"] = summary
    if run_name:
        config["run_name"] = run_name

    run = await repo.create_evaluation_run(
        db_session,
        evaluation_set_id=evset.id,
        status=status,
        config=config,
    )

    created_results = []
    for item in results or []:
        question = await repo.create_evaluation_question(
            db_session,
            evaluation_set_id=evset.id,
            question=item.get("question", f"Q-{uuid4().hex[:6]}?"),
            difficulty=item.get("difficulty"),
            metadata={"tags": item.get("tags", [])},
        )
        result = await repo.create_evaluation_result(
            db_session,
            evaluation_run_id=run.id,
            evaluation_question_id=question.id,
            retrieval_score=item.get("retrieval_score"),
            faithfulness_score=item.get("faithfulness_score"),
            citation_accuracy_score=item.get("citation_accuracy_score"),
            answer_relevance_score=item.get("answer_relevance_score"),
            generated_answer=item.get("generated_answer"),
            details=item.get("details", {}),
        )
        created_results.append((result, question))

    await db_session.commit()
    return run, created_results


# ---------------------------------------------------------------------------
# GET /evaluations/runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_evaluation_runs_returns_org_runs(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_a, _ = await _seed_run_with_results(db_session, org=org, repo=repo)
    run_b, _ = await _seed_run_with_results(db_session, org=org, repo=repo)

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/runs",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] >= 2
    run_ids = {item["evaluation_run_id"] for item in payload["items"]}
    assert str(run_a.id) in run_ids
    assert str(run_b.id) in run_ids


@pytest.mark.asyncio
async def test_list_evaluation_runs_isolates_organizations(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    _, other_org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    foreign_run, _ = await _seed_run_with_results(db_session, org=other_org, repo=repo)

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/runs",
        headers=_headers(token=token, org_id=str(org.id)),
    )
    assert response.status_code == 200
    run_ids = {item["evaluation_run_id"] for item in response.json()["items"]}
    assert str(foreign_run.id) not in run_ids


@pytest.mark.asyncio
async def test_list_evaluation_runs_filters_by_status(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_ok, _ = await _seed_run_with_results(
        db_session, org=org, repo=repo, status=EvaluationRunStatus.completed.value
    )
    run_fail, _ = await _seed_run_with_results(
        db_session, org=org, repo=repo, status=EvaluationRunStatus.failed.value
    )

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/runs",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"status": "completed"},
    )
    assert response.status_code == 200
    run_ids = {item["evaluation_run_id"] for item in response.json()["items"]}
    assert str(run_ok.id) in run_ids
    assert str(run_fail.id) not in run_ids


# ---------------------------------------------------------------------------
# GET /evaluations/compare – metric delta calculations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_returns_metric_deltas(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_a, _ = await _seed_run_with_results(
        db_session,
        org=org,
        repo=repo,
        summary={
            "retrieval_hit_rate": 0.80,
            "citation_accuracy_score": 0.90,
            "faithfulness_score": 0.75,
        },
    )
    run_b, _ = await _seed_run_with_results(
        db_session,
        org=org,
        repo=repo,
        summary={
            "retrieval_hit_rate": 0.70,  # regression
            "citation_accuracy_score": 0.95,  # improvement
            "faithfulness_score": 0.75,  # unchanged
        },
    )

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_a"]["evaluation_run_id"] == str(run_a.id)
    assert payload["run_b"]["evaluation_run_id"] == str(run_b.id)

    deltas_by_metric = {d["metric"]: d for d in payload["metric_deltas"]}
    assert "retrieval_hit_rate" in deltas_by_metric
    assert deltas_by_metric["retrieval_hit_rate"]["is_regression"] is True
    assert deltas_by_metric["retrieval_hit_rate"]["is_improvement"] is False

    assert "citation_accuracy_score" in deltas_by_metric
    assert deltas_by_metric["citation_accuracy_score"]["is_improvement"] is True
    assert deltas_by_metric["citation_accuracy_score"]["is_regression"] is False

    assert "faithfulness_score" in deltas_by_metric
    assert deltas_by_metric["faithfulness_score"]["is_regression"] is False
    assert deltas_by_metric["faithfulness_score"]["is_improvement"] is False


@pytest.mark.asyncio
async def test_compare_delta_values_are_accurate(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_a, _ = await _seed_run_with_results(
        db_session, org=org, repo=repo, summary={"retrieval_hit_rate": 0.60}
    )
    run_b, _ = await _seed_run_with_results(
        db_session, org=org, repo=repo, summary={"retrieval_hit_rate": 0.85}
    )

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id)},
    )
    assert response.status_code == 200
    deltas = {d["metric"]: d for d in response.json()["metric_deltas"]}
    delta_val = deltas["retrieval_hit_rate"]["delta"]
    assert delta_val is not None
    assert abs(delta_val - 0.25) < 1e-6
    assert deltas["retrieval_hit_rate"]["is_improvement"] is True


@pytest.mark.asyncio
async def test_compare_lower_is_better_metrics(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_a, _ = await _seed_run_with_results(
        db_session, org=org, repo=repo, summary={"not_found_rate": 0.10}
    )
    run_b, _ = await _seed_run_with_results(
        db_session,
        org=org,
        repo=repo,
        summary={"not_found_rate": 0.25},  # got worse
    )

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id)},
    )
    assert response.status_code == 200
    deltas = {d["metric"]: d for d in response.json()["metric_deltas"]}
    assert deltas["not_found_rate"]["is_regression"] is True
    assert deltas["not_found_rate"]["is_improvement"] is False


# ---------------------------------------------------------------------------
# GET /evaluations/compare – regression/improvement counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_counts_case_regressions(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()

    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="Shared Set")
    q1 = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Q1 regressed?"
    )
    q2 = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Q2 stable?"
    )

    run_a = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )
    # Q1: succeeded in run_a with high score
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_a.id,
        evaluation_question_id=q1.id,
        retrieval_score=0.90,
        details={"status": "completed"},
    )
    # Q2: succeeded in run_a
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_a.id,
        evaluation_question_id=q2.id,
        retrieval_score=0.85,
        details={"status": "completed"},
    )

    run_b = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )
    # Q1: failed in run_b → regression
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_b.id,
        evaluation_question_id=q1.id,
        retrieval_score=None,
        details={"status": "failed", "error": "Retrieval timeout"},
    )
    # Q2: still passes in run_b
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_b.id,
        evaluation_question_id=q2.id,
        retrieval_score=0.87,
        details={"status": "completed"},
    )
    await db_session.commit()

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["regression_count"] >= 1
    regressed_cases = [c for c in payload["cases"] if c["regression"]]
    assert any(c["evaluation_question_id"] == str(q1.id) for c in regressed_cases)


@pytest.mark.asyncio
async def test_compare_counts_case_improvements(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()

    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Improvement Set"
    )
    q1 = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Q improved?"
    )

    run_a = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.failed.value
    )
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_a.id,
        evaluation_question_id=q1.id,
        details={"status": "failed", "error": "LLM error"},
    )

    run_b = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_b.id,
        evaluation_question_id=q1.id,
        retrieval_score=0.88,
        details={"status": "completed"},
    )
    await db_session.commit()

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id)},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["improvement_count"] >= 1
    improved_cases = [c for c in payload["cases"] if c["improvement"]]
    assert any(c["evaluation_question_id"] == str(q1.id) for c in improved_cases)


# ---------------------------------------------------------------------------
# GET /evaluations/compare – case filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_filters_by_difficulty(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()

    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Difficulty Set"
    )
    q_easy = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Easy Q?", difficulty="easy"
    )
    q_hard = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Hard Q?", difficulty="hard"
    )

    run_a = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )
    run_b = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )
    for q in (q_easy, q_hard):
        for run in (run_a, run_b):
            await repo.create_evaluation_result(
                db_session,
                evaluation_run_id=run.id,
                evaluation_question_id=q.id,
                details={"status": "completed"},
            )
    await db_session.commit()

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id), "difficulty": "hard"},
    )
    assert response.status_code == 200
    payload = response.json()
    question_ids = {c["evaluation_question_id"] for c in payload["cases"]}
    assert str(q_hard.id) in question_ids
    assert str(q_easy.id) not in question_ids


@pytest.mark.asyncio
async def test_compare_filters_by_case_status_regression(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()

    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Status Filter Set"
    )
    q_reg = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Regression Q?"
    )
    q_ok = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Stable Q?"
    )

    run_a = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )
    run_b = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )

    # q_reg: passes in run_a, fails in run_b
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_a.id,
        evaluation_question_id=q_reg.id,
        details={"status": "completed"},
    )
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_b.id,
        evaluation_question_id=q_reg.id,
        details={"status": "failed", "error": "timeout"},
    )
    # q_ok: passes in both
    for run in (run_a, run_b):
        await repo.create_evaluation_result(
            db_session,
            evaluation_run_id=run.id,
            evaluation_question_id=q_ok.id,
            details={"status": "completed"},
        )
    await db_session.commit()

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id), "case_status": "regression"},
    )
    assert response.status_code == 200
    payload = response.json()
    question_ids = {c["evaluation_question_id"] for c in payload["cases"]}
    assert str(q_reg.id) in question_ids
    assert str(q_ok.id) not in question_ids


# ---------------------------------------------------------------------------
# GET /evaluations/compare – org isolation and 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compare_404_for_foreign_run(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    _, other_org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()

    run_own, _ = await _seed_run_with_results(db_session, org=org, repo=repo)
    run_foreign, _ = await _seed_run_with_results(db_session, org=other_org, repo=repo)

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_own.id), "run_b": str(run_foreign.id)},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_compare_404_for_nonexistent_run(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_own, _ = await _seed_run_with_results(db_session, org=org, repo=repo)

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_own.id), "run_b": str(uuid4())},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_compare_viewer_can_read(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    viewer, org = await _seed_org_and_user(db_session, role=OrganizationRole.viewer)
    repo = EvaluationRepository()
    run_a, _ = await _seed_run_with_results(db_session, org=org, repo=repo)
    run_b, _ = await _seed_run_with_results(db_session, org=org, repo=repo)

    token = _token(viewer, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id)},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /evaluations/compare/export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_comparison_csv_returns_csv(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_a, _ = await _seed_run_with_results(
        db_session,
        org=org,
        repo=repo,
        run_name="Baseline",
        summary={"retrieval_hit_rate": 0.80, "citation_accuracy_score": 0.90},
        results=[{"question": "What is RAG?", "details": {"status": "completed"}}],
    )
    run_b, _ = await _seed_run_with_results(
        db_session,
        org=org,
        repo=repo,
        run_name="Candidate",
        summary={"retrieval_hit_rate": 0.70, "citation_accuracy_score": 0.95},
        results=[{"question": "What is RAG?", "details": {"status": "completed"}}],
    )

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare/export",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id), "format": "csv"},
    )
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    content = response.text
    assert "Metric Summary" in content
    assert "Retrieval Hit Rate" in content
    assert "Citation Accuracy" in content
    assert "Case Comparison" in content


@pytest.mark.asyncio
async def test_export_comparison_csv_marks_regressions(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_a, _ = await _seed_run_with_results(
        db_session,
        org=org,
        repo=repo,
        summary={"retrieval_hit_rate": 0.90},
    )
    run_b, _ = await _seed_run_with_results(
        db_session,
        org=org,
        repo=repo,
        summary={"retrieval_hit_rate": 0.50},  # large drop
    )

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare/export",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id), "format": "csv"},
    )
    assert response.status_code == 200
    assert "regression" in response.text


@pytest.mark.asyncio
async def test_export_comparison_json_returns_json(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()
    run_a, _ = await _seed_run_with_results(
        db_session, org=org, repo=repo, summary={"retrieval_hit_rate": 0.80}
    )
    run_b, _ = await _seed_run_with_results(
        db_session, org=org, repo=repo, summary={"retrieval_hit_rate": 0.85}
    )

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare/export",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id), "format": "json"},
    )
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    parsed = json.loads(response.content)
    assert "metric_deltas" in parsed
    assert "cases" in parsed
    assert "regression_count" in parsed


@pytest.mark.asyncio
async def test_export_includes_failing_cases(
    comparison_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user, org = await _seed_org_and_user(db_session)
    repo = EvaluationRepository()

    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name="Export Cases"
    )
    q1 = await repo.create_evaluation_question(
        db_session, evaluation_set_id=evset.id, question="Failing case question?"
    )
    run_a = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )
    run_b = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status=EvaluationRunStatus.completed.value
    )
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_a.id,
        evaluation_question_id=q1.id,
        details={"status": "completed"},
    )
    await repo.create_evaluation_result(
        db_session,
        evaluation_run_id=run_b.id,
        evaluation_question_id=q1.id,
        details={"status": "failed", "error": "timeout"},
    )
    await db_session.commit()

    token = _token(user, org)
    response = await comparison_client.get(
        "/api/v1/evaluations/compare/export",
        headers=_headers(token=token, org_id=str(org.id)),
        params={"run_a": str(run_a.id), "run_b": str(run_b.id), "format": "json"},
    )
    assert response.status_code == 200
    parsed = json.loads(response.content)
    assert parsed["regression_count"] >= 1
    regressed = [c for c in parsed["cases"] if c["regression"]]
    assert any(c["evaluation_question_id"] == str(q1.id) for c in regressed)


# ---------------------------------------------------------------------------
# Repository unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_all_results_for_run_returns_all_rows(
    db_session: AsyncSession,
) -> None:
    org = Organization(name=f"Org-{uuid4().hex[:6]}", slug=f"org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(db_session, organization_id=org.id, name="All Results")
    run = await repo.create_evaluation_run(
        db_session,
        evaluation_set_id=evset.id,
        status=EvaluationRunStatus.completed.value,
    )
    for i in range(5):
        q = await repo.create_evaluation_question(
            db_session, evaluation_set_id=evset.id, question=f"Q{i}?"
        )
        await repo.create_evaluation_result(
            db_session,
            evaluation_run_id=run.id,
            evaluation_question_id=q.id,
            details={},
        )
    await db_session.flush()

    rows = await repo.list_all_evaluation_results_for_run(db_session, evaluation_run_id=run.id)
    assert len(rows) == 5
    for result, _question in rows:
        assert result.evaluation_run_id == run.id


@pytest.mark.asyncio
async def test_count_evaluation_runs_for_organization(
    db_session: AsyncSession,
) -> None:
    org = Organization(name=f"Org-{uuid4().hex[:6]}", slug=f"org-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    other_org = Organization(name=f"OtherOrg-{uuid4().hex[:6]}", slug=f"other-{uuid4().hex[:8]}")
    db_session.add(other_org)
    await db_session.flush()

    repo = EvaluationRepository()
    for org_target in (org, other_org):
        evset = await repo.create_evaluation_set(
            db_session, organization_id=org_target.id, name=f"Set-{uuid4().hex[:4]}"
        )
        await repo.create_evaluation_run(
            db_session,
            evaluation_set_id=evset.id,
            status=EvaluationRunStatus.completed.value,
        )
    await db_session.flush()

    count = await repo.count_evaluation_runs_for_organization(db_session, organization_id=org.id)
    assert count == 1

    other_count = await repo.count_evaluation_runs_for_organization(
        db_session, organization_id=other_org.id
    )
    assert other_count == 1
