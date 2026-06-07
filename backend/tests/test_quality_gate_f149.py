"""Backend tests for F149: Evaluation-based release quality gates.

Covers:
  A. Quality gate service — threshold evaluation logic (unit tests)
  B. Quality gate CRUD API — create, list, get, update, delete
  C. Gate run trigger — evaluation run gating with passing/failing metrics
  D. Gate run trigger — safety eval run gating
  E. Override endpoint — documented reason, audit trail, idempotency
  F. Gate report endpoint — full report structure and ci_exit_code
  G. Repository — org isolation, gate run list
  H. Role guards — non-admin users cannot create/trigger/override

Run:
    pytest tests/test_quality_gate_f149.py -v
"""

from __future__ import annotations

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
from app.domains.quality_gates.repositories.quality_gates import QualityGateRepository
from app.domains.quality_gates.schemas.quality_gates import QualityGateThresholds
from app.domains.quality_gates.services.quality_gate_service import evaluate_gate
from app.domains.safety_evals.repositories.safety_evals import SafetyEvalRepository
from app.main import app
from app.models.enums import OrganizationRole, QualityGateVerdict
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def gate_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    get_auth_provider.cache_clear()

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


async def _make_org_user(
    db_session: AsyncSession,
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


def _token(user: User, org: Organization) -> str:
    return create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )


def _headers(user: User, org: Organization) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(user, org)}",
        "X-Organization-ID": str(org.id),
    }


async def _seed_eval_run(
    db_session: AsyncSession,
    org: Organization,
    *,
    summary: dict | None = None,
) -> str:
    repo = EvaluationRepository()
    evset = await repo.create_evaluation_set(
        db_session, organization_id=org.id, name=f"Set-{uuid4().hex[:6]}"
    )
    config = {"metrics_summary": summary} if summary else {}
    run = await repo.create_evaluation_run(
        db_session, evaluation_set_id=evset.id, status="completed", config=config
    )
    await db_session.commit()
    return str(run.id)


async def _seed_safety_run(
    db_session: AsyncSession,
    org: Organization,
    *,
    pass_rate: float = 1.0,
) -> str:
    repo = SafetyEvalRepository()
    pass_count = int(pass_rate * 10)
    total_count = 10
    run = await repo.create_run(
        db_session,
        organization_id=org.id,
        suite_name="test-suite",
        config={},
    )
    await repo.update_run_status(
        db_session,
        run_id=run.id,
        status="completed",
        mark_completed=True,
        pass_count=pass_count,
        fail_count=total_count - pass_count,
        total_count=total_count,
        summary={"pass_rate": pass_rate},
    )
    await db_session.commit()
    return str(run.id)


# ===========================================================================
# A. Quality gate service — threshold evaluation logic (unit tests)
# ===========================================================================


def test_evaluate_gate_all_pass():
    thresholds = QualityGateThresholds(
        retrieval_hit_rate_min=0.7,
        faithfulness_score_min=0.8,
        not_found_rate_max=0.1,
        safety_pass_rate_min=0.95,
    )
    eval_summary = {
        "retrieval_hit_rate": 0.85,
        "faithfulness_score": 0.90,
        "not_found_rate": 0.05,
    }
    safety_summary = {"pass_rate": 1.0}

    verdict, passed, failed = evaluate_gate(thresholds, eval_summary, safety_summary)

    assert verdict == QualityGateVerdict.passed.value
    assert len(failed) == 0
    assert len(passed) == 4


def test_evaluate_gate_metric_below_threshold_fails():
    thresholds = QualityGateThresholds(
        retrieval_hit_rate_min=0.9,
        citation_accuracy_score_min=0.8,
    )
    eval_summary = {"retrieval_hit_rate": 0.65, "citation_accuracy_score": 0.85}

    verdict, passed, failed = evaluate_gate(thresholds, eval_summary, None)

    assert verdict == QualityGateVerdict.failed.value
    assert any(c.metric == "retrieval_hit_rate_min" for c in failed)
    assert any(c.metric == "citation_accuracy_score_min" for c in passed)


def test_evaluate_gate_not_found_rate_max_fails():
    thresholds = QualityGateThresholds(not_found_rate_max=0.05)
    eval_summary = {"not_found_rate": 0.15}

    verdict, passed, failed = evaluate_gate(thresholds, eval_summary, None)

    assert verdict == QualityGateVerdict.failed.value
    assert any(c.metric == "not_found_rate_max" for c in failed)
    check = next(c for c in failed if c.metric == "not_found_rate_max")
    assert check.actual == pytest.approx(0.15)
    assert check.threshold == pytest.approx(0.05)
    assert check.detail is not None


def test_evaluate_gate_missing_metric_fails():
    thresholds = QualityGateThresholds(faithfulness_score_min=0.8)
    eval_summary = {}

    verdict, passed, failed = evaluate_gate(thresholds, eval_summary, None)

    assert verdict == QualityGateVerdict.failed.value
    assert failed[0].actual is None
    assert "not available" in (failed[0].detail or "")


def test_evaluate_gate_safety_pass_rate_fails():
    thresholds = QualityGateThresholds(safety_pass_rate_min=0.95)
    safety_summary = {"pass_rate": 0.80}

    verdict, passed, failed = evaluate_gate(thresholds, None, safety_summary)

    assert verdict == QualityGateVerdict.failed.value
    assert any(c.metric == "safety_pass_rate_min" for c in failed)


def test_evaluate_gate_no_thresholds_configured():
    thresholds = QualityGateThresholds()
    verdict, passed, failed = evaluate_gate(thresholds, {"retrieval_hit_rate": 0.1}, {})
    assert verdict == QualityGateVerdict.passed.value
    assert passed == []
    assert failed == []


# ===========================================================================
# B. Quality gate CRUD API
# ===========================================================================


@pytest.mark.asyncio
async def test_create_quality_gate(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)

    resp = await gate_client.post(
        "/api/v1/quality-gates",
        json={
            "name": "v0.5 Release Gate",
            "description": "Release criteria for v0.5.0",
            "thresholds": {"retrieval_hit_rate_min": 0.8, "safety_pass_rate_min": 0.95},
        },
        headers=_headers(user, org),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "v0.5 Release Gate"
    assert body["thresholds"]["retrieval_hit_rate_min"] == pytest.approx(0.8)
    assert "quality_gate_id" in body


@pytest.mark.asyncio
async def test_list_quality_gates(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    for i in range(3):
        await repo.create_gate(
            db_session,
            organization_id=org.id,
            name=f"Gate {i}",
            description=None,
            thresholds={},
            baseline_evaluation_run_id=None,
            baseline_safety_run_id=None,
            created_by_id=user.id,
        )
    await db_session.commit()

    resp = await gate_client.get("/api/v1/quality-gates", headers=_headers(user, org))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 3
    assert len(body["items"]) >= 3


@pytest.mark.asyncio
async def test_get_quality_gate(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="My Gate",
        description="desc",
        thresholds={"faithfulness_score_min": 0.75},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    resp = await gate_client.get(f"/api/v1/quality-gates/{gate.id}", headers=_headers(user, org))
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "My Gate"
    assert body["thresholds"]["faithfulness_score_min"] == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_get_quality_gate_not_found(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    resp = await gate_client.get(f"/api/v1/quality-gates/{uuid4()}", headers=_headers(user, org))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_quality_gate(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Old Name",
        description=None,
        thresholds={},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    resp = await gate_client.patch(
        f"/api/v1/quality-gates/{gate.id}",
        json={"name": "New Name", "thresholds": {"retrieval_hit_rate_min": 0.9}},
        headers=_headers(user, org),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["thresholds"]["retrieval_hit_rate_min"] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_delete_quality_gate(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="To Delete",
        description=None,
        thresholds={},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    resp = await gate_client.delete(f"/api/v1/quality-gates/{gate.id}", headers=_headers(user, org))
    assert resp.status_code == 204

    resp2 = await gate_client.get(f"/api/v1/quality-gates/{gate.id}", headers=_headers(user, org))
    assert resp2.status_code == 404


# ===========================================================================
# C. Gate run trigger — evaluation run gating
# ===========================================================================


@pytest.mark.asyncio
async def test_trigger_gate_run_passes(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Pass Gate",
        description=None,
        thresholds={"retrieval_hit_rate_min": 0.7, "faithfulness_score_min": 0.6},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"retrieval_hit_rate": 0.85, "faithfulness_score": 0.75},
    )

    resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["verdict"] == "passed"
    assert len(body["failed_checks"]) == 0
    assert len(body["passed_checks"]) == 2


@pytest.mark.asyncio
async def test_trigger_gate_run_fails(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Strict Gate",
        description=None,
        thresholds={"retrieval_hit_rate_min": 0.95, "citation_accuracy_score_min": 0.9},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"retrieval_hit_rate": 0.60, "citation_accuracy_score": 0.55},
    )

    resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["verdict"] == "failed"
    assert len(body["failed_checks"]) == 2
    assert len(body["passed_checks"]) == 0


@pytest.mark.asyncio
async def test_trigger_gate_run_no_run_ids_rejected(
    gate_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Gate",
        description=None,
        thresholds={},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={},
        headers=_headers(user, org),
    )
    assert resp.status_code == 422


# ===========================================================================
# D. Gate run trigger — safety eval run gating
# ===========================================================================


@pytest.mark.asyncio
async def test_trigger_gate_run_with_safety_eval_passes(
    gate_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Safety Gate",
        description=None,
        thresholds={"safety_pass_rate_min": 0.9},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    safety_run_id = await _seed_safety_run(db_session, org, pass_rate=1.0)

    resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"safety_eval_run_id": safety_run_id},
        headers=_headers(user, org),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["verdict"] == "passed"
    assert body["safety_eval_run_id"] == safety_run_id


@pytest.mark.asyncio
async def test_trigger_gate_run_with_safety_eval_fails(
    gate_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Safety Gate Strict",
        description=None,
        thresholds={"safety_pass_rate_min": 0.95},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    safety_run_id = await _seed_safety_run(db_session, org, pass_rate=0.70)

    resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"safety_eval_run_id": safety_run_id},
        headers=_headers(user, org),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["verdict"] == "failed"
    assert any(c["metric"] == "safety_pass_rate_min" for c in body["failed_checks"])


# ===========================================================================
# E. Override endpoint
# ===========================================================================


@pytest.mark.asyncio
async def test_override_failed_gate_run(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Overridable Gate",
        description=None,
        thresholds={"retrieval_hit_rate_min": 0.99},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(db_session, org, summary={"retrieval_hit_rate": 0.50})
    run_resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    assert run_resp.status_code == 201
    gate_run_id = run_resp.json()["gate_run_id"]
    assert run_resp.json()["verdict"] == "failed"

    override_resp = await gate_client.post(
        f"/api/v1/quality-gates/runs/{gate_run_id}/override",
        json={
            "reason": "Approved by engineering lead — known retrieval regression in fixture data."
        },
        headers=_headers(user, org),
    )
    assert override_resp.status_code == 200
    body = override_resp.json()
    assert body["verdict"] == "overridden"
    assert "Approved by engineering lead" in (body["override_reason"] or "")
    assert body["overridden_at"] is not None


@pytest.mark.asyncio
async def test_override_passed_gate_run_rejected(
    gate_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Pass Gate",
        description=None,
        thresholds={"retrieval_hit_rate_min": 0.5},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(db_session, org, summary={"retrieval_hit_rate": 0.9})
    run_resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    gate_run_id = run_resp.json()["gate_run_id"]

    resp = await gate_client.post(
        f"/api/v1/quality-gates/runs/{gate_run_id}/override",
        json={"reason": "This should be rejected by the API endpoint."},
        headers=_headers(user, org),
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_override_short_reason_rejected(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Gate",
        description=None,
        thresholds={"retrieval_hit_rate_min": 0.99},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(db_session, org, summary={"retrieval_hit_rate": 0.1})
    run_resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    gate_run_id = run_resp.json()["gate_run_id"]

    resp = await gate_client.post(
        f"/api/v1/quality-gates/runs/{gate_run_id}/override",
        json={"reason": "short"},
        headers=_headers(user, org),
    )
    assert resp.status_code == 422


# ===========================================================================
# F. Gate report endpoint
# ===========================================================================


@pytest.mark.asyncio
async def test_gate_report_passed_has_exit_code_0(
    gate_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Report Gate",
        description=None,
        thresholds={"retrieval_hit_rate_min": 0.5},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(db_session, org, summary={"retrieval_hit_rate": 0.9})
    run_resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    gate_run_id = run_resp.json()["gate_run_id"]

    report_resp = await gate_client.get(
        f"/api/v1/quality-gates/runs/{gate_run_id}/report",
        headers=_headers(user, org),
    )
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert report["verdict"] == "passed"
    assert report["ci_exit_code"] == 0
    assert report["pass_count"] == 1
    assert report["fail_count"] == 0
    assert "thresholds_applied" in report
    assert "generated_at" in report


@pytest.mark.asyncio
async def test_gate_report_failed_has_exit_code_1(
    gate_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Failing Report Gate",
        description=None,
        thresholds={"retrieval_hit_rate_min": 0.99},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(db_session, org, summary={"retrieval_hit_rate": 0.50})
    run_resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    gate_run_id = run_resp.json()["gate_run_id"]

    report_resp = await gate_client.get(
        f"/api/v1/quality-gates/runs/{gate_run_id}/report",
        headers=_headers(user, org),
    )
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert report["verdict"] == "failed"
    assert report["ci_exit_code"] == 1
    assert report["fail_count"] == 1


@pytest.mark.asyncio
async def test_gate_report_overridden_has_exit_code_0(
    gate_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Override Gate",
        description=None,
        thresholds={"retrieval_hit_rate_min": 0.99},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(db_session, org, summary={"retrieval_hit_rate": 0.50})
    run_resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    gate_run_id = run_resp.json()["gate_run_id"]

    await gate_client.post(
        f"/api/v1/quality-gates/runs/{gate_run_id}/override",
        json={"reason": "CTO-approved: metric known to be skewed in staging data."},
        headers=_headers(user, org),
    )

    report_resp = await gate_client.get(
        f"/api/v1/quality-gates/runs/{gate_run_id}/report",
        headers=_headers(user, org),
    )
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert report["verdict"] == "overridden"
    assert report["ci_exit_code"] == 0
    assert "CTO-approved" in (report["override_reason"] or "")


# ===========================================================================
# G. Repository — org isolation
# ===========================================================================


@pytest.mark.asyncio
async def test_gate_org_isolation(gate_client: AsyncClient, db_session: AsyncSession):
    user_a, org_a = await _make_org_user(db_session)
    user_b, org_b = await _make_org_user(db_session)

    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org_a.id,
        name="Org A Gate",
        description=None,
        thresholds={},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user_a.id,
    )
    await db_session.commit()

    resp = await gate_client.get(
        f"/api/v1/quality-gates/{gate.id}", headers=_headers(user_b, org_b)
    )
    assert resp.status_code == 404


# ===========================================================================
# H. Role guards
# ===========================================================================


@pytest.mark.asyncio
async def test_member_cannot_create_gate(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session, role=OrganizationRole.member)

    resp = await gate_client.post(
        "/api/v1/quality-gates",
        json={"name": "Should Fail"},
        headers=_headers(user, org),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_can_list_gates(gate_client: AsyncClient, db_session: AsyncSession):
    user, org = await _make_org_user(db_session, role=OrganizationRole.viewer)

    resp = await gate_client.get("/api/v1/quality-gates", headers=_headers(user, org))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_member_cannot_trigger_gate_run(gate_client: AsyncClient, db_session: AsyncSession):
    admin, org = await _make_org_user(db_session)
    member = User(
        organization_id=org.id,
        external_auth_id=f"u-{uuid4().hex[:8]}",
        email=f"m-{uuid4().hex[:8]}@test.com",
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=member.id, role=OrganizationRole.member.value
        )
    )

    repo = QualityGateRepository()
    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Gate",
        description=None,
        thresholds={},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=admin.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(db_session, org, summary={})

    resp = await gate_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers={
            "Authorization": f"Bearer {_token(member, org)}",
            "X-Organization-ID": str(org.id),
        },
    )
    assert resp.status_code == 403
