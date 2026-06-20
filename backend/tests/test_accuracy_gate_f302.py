"""Backend tests for F302: Evaluation-based accuracy gates in CI/CD.

Covers:
  A. Refusal accuracy threshold — new metric in evaluate_gate()
  B. Regression detection — evaluate_regression() with/without delta_max
  C. Regression deltas included in baseline_comparison report
  D. Gate verdict flips to failed when regression threshold exceeded
  E. API: gate run report includes baseline_comparison when gate has baseline
  F. API: refusal_accuracy_score_min threshold enforced via gate run
  G. Threshold schema — validation of new fields
  H. JUnit XML generation from accuracy_eval_runner script (unit tests)
  I. build_gate_report — baseline_comparison included in report dict
  J. Org isolation — baseline run from another org is not accessible

Run:
    pytest tests/test_accuracy_gate_f302.py -v
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
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
from app.domains.quality_gates.services.quality_gate_service import (
    build_gate_report,
    evaluate_gate,
    evaluate_regression,
)
from app.main import app
from app.models.enums import OrganizationRole, QualityGateVerdict
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def f302_client(
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


def _headers(user: User, org: Organization) -> dict[str, str]:
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    return {
        "Authorization": f"Bearer {token}",
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


# ===========================================================================
# A. Refusal accuracy threshold
# ===========================================================================


def test_refusal_accuracy_passes_when_above_threshold():
    thresholds = QualityGateThresholds(refusal_accuracy_score_min=0.85)
    eval_summary = {"refusal_accuracy_score": 0.92}

    verdict, passed, failed = evaluate_gate(thresholds, eval_summary, None)

    assert verdict == QualityGateVerdict.passed.value
    assert any(c.metric == "refusal_accuracy_score_min" for c in passed)
    assert len(failed) == 0


def test_refusal_accuracy_fails_when_below_threshold():
    thresholds = QualityGateThresholds(refusal_accuracy_score_min=0.90)
    eval_summary = {"refusal_accuracy_score": 0.70}

    verdict, _passed, failed = evaluate_gate(thresholds, eval_summary, None)

    assert verdict == QualityGateVerdict.failed.value
    check = next(c for c in failed if c.metric == "refusal_accuracy_score_min")
    assert check.actual == pytest.approx(0.70)
    assert check.threshold == pytest.approx(0.90)
    assert check.detail is not None


def test_refusal_accuracy_missing_metric_fails():
    thresholds = QualityGateThresholds(refusal_accuracy_score_min=0.80)
    eval_summary = {}  # metric absent

    verdict, _passed, failed = evaluate_gate(thresholds, eval_summary, None)

    assert verdict == QualityGateVerdict.failed.value
    check = next(c for c in failed if c.metric == "refusal_accuracy_score_min")
    assert check.actual is None
    assert "not available" in (check.detail or "")


def test_refusal_accuracy_combined_with_other_metrics():
    thresholds = QualityGateThresholds(
        retrieval_hit_rate_min=0.80,
        refusal_accuracy_score_min=0.88,
        faithfulness_score_min=0.75,
    )
    eval_summary = {
        "retrieval_hit_rate": 0.85,
        "refusal_accuracy_score": 0.90,
        "faithfulness_score": 0.80,
    }

    verdict, passed, failed = evaluate_gate(thresholds, eval_summary, None)

    assert verdict == QualityGateVerdict.passed.value
    assert len(failed) == 0
    assert len(passed) == 3


# ===========================================================================
# B. Regression detection — evaluate_regression()
# ===========================================================================


def test_regression_no_delta_when_delta_max_not_set():
    thresholds = QualityGateThresholds()  # regression_delta_max not set
    current = {"retrieval_hit_rate": 0.75, "faithfulness_score": 0.70}
    baseline = {"retrieval_hit_rate": 0.85, "faithfulness_score": 0.80}

    regression_failed, deltas = evaluate_regression(thresholds, current, baseline)

    assert regression_failed == []
    assert len(deltas) > 0
    rhr = next(d for d in deltas if d.metric == "retrieval_hit_rate")
    assert rhr.delta == pytest.approx(-0.10, abs=1e-6)
    # regressed flag stays False when no threshold is set
    assert rhr.regressed is False


def test_regression_fails_when_drop_exceeds_delta_max():
    thresholds = QualityGateThresholds(regression_delta_max=0.05)
    current = {"retrieval_hit_rate": 0.70, "faithfulness_score": 0.82}
    baseline = {"retrieval_hit_rate": 0.85, "faithfulness_score": 0.80}

    regression_failed, deltas = evaluate_regression(thresholds, current, baseline)

    # retrieval dropped 0.15 > 0.05 → regression
    assert any(c.metric == "regression:retrieval_hit_rate" for c in regression_failed)
    # faithfulness improved 0.02 → no regression
    assert not any(c.metric == "regression:faithfulness_score" for c in regression_failed)

    rhr_delta = next(d for d in deltas if d.metric == "retrieval_hit_rate")
    assert rhr_delta.regressed is True


def test_regression_passes_when_drop_within_delta_max():
    thresholds = QualityGateThresholds(regression_delta_max=0.10)
    current = {"retrieval_hit_rate": 0.82}
    baseline = {"retrieval_hit_rate": 0.85}

    regression_failed, deltas = evaluate_regression(thresholds, current, baseline)

    assert regression_failed == []
    rhr = next(d for d in deltas if d.metric == "retrieval_hit_rate")
    assert rhr.regressed is False


def test_regression_no_baseline_returns_empty():
    thresholds = QualityGateThresholds(regression_delta_max=0.05)
    current = {"retrieval_hit_rate": 0.70}

    regression_failed, deltas = evaluate_regression(thresholds, current, None)

    assert regression_failed == []
    assert deltas == []


def test_regression_missing_metric_in_current_skipped():
    thresholds = QualityGateThresholds(regression_delta_max=0.05)
    current = {}  # metric absent from current run
    baseline = {"retrieval_hit_rate": 0.85}

    regression_failed, deltas = evaluate_regression(thresholds, current, baseline)

    # delta is None when current is missing; should not generate a regression check
    assert regression_failed == []
    assert any(d.metric == "retrieval_hit_rate" for d in deltas)
    rhr = next(d for d in deltas if d.metric == "retrieval_hit_rate")
    assert rhr.current is None
    assert rhr.delta is None
    assert rhr.regressed is False


def test_regression_refusal_accuracy_tracked():
    thresholds = QualityGateThresholds(regression_delta_max=0.05)
    current = {"refusal_accuracy_score": 0.72}
    baseline = {"refusal_accuracy_score": 0.91}

    regression_failed, deltas = evaluate_regression(thresholds, current, baseline)

    assert any(c.metric == "regression:refusal_accuracy_score" for c in regression_failed)
    delta = next(d for d in deltas if d.metric == "refusal_accuracy_score")
    assert delta.regressed is True


# ===========================================================================
# C. Regression deltas in build_gate_report
# ===========================================================================


def test_build_gate_report_includes_baseline_comparison():
    from app.domains.quality_gates.schemas.quality_gates import BaselineMetricDelta

    thresholds = QualityGateThresholds(regression_delta_max=0.05)
    deltas = [
        BaselineMetricDelta(
            metric="retrieval_hit_rate",
            label="Retrieval Hit Rate",
            baseline=0.85,
            current=0.82,
            delta=-0.03,
            regressed=False,
        )
    ]
    report = build_gate_report(
        gate_run_id="fake-id",
        quality_gate_id="gate-1",
        quality_gate_name="Test Gate",
        verdict="passed",
        evaluation_run_id="run-1",
        safety_eval_run_id=None,
        thresholds=thresholds,
        passed_checks=[],
        failed_checks=[],
        evaluation_summary={"retrieval_hit_rate": 0.82},
        safety_summary=None,
        baseline_comparison=deltas,
    )

    assert "baseline_comparison" in report
    bc = report["baseline_comparison"]
    assert len(bc) == 1
    assert bc[0]["metric"] == "retrieval_hit_rate"
    assert bc[0]["delta"] == pytest.approx(-0.03, abs=1e-6)
    assert bc[0]["regressed"] is False


def test_build_gate_report_no_baseline_comparison_key_absent():
    thresholds = QualityGateThresholds()
    report = build_gate_report(
        gate_run_id="fake-id",
        quality_gate_id="gate-1",
        quality_gate_name="Test Gate",
        verdict="passed",
        evaluation_run_id=None,
        safety_eval_run_id=None,
        thresholds=thresholds,
        passed_checks=[],
        failed_checks=[],
        evaluation_summary=None,
        safety_summary=None,
    )
    assert "baseline_comparison" not in report


# ===========================================================================
# D. Gate verdict flips to failed when regression threshold exceeded (API)
# ===========================================================================


@pytest.mark.asyncio
async def test_gate_run_with_baseline_regression_fails(
    f302_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()

    # Seed baseline run with healthy metrics
    baseline_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"retrieval_hit_rate": 0.85, "faithfulness_score": 0.82},
    )

    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Regression Gate",
        description=None,
        thresholds={"regression_delta_max": 0.05},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    # Update the gate's baseline_evaluation_run_id
    from uuid import UUID

    gate.baseline_evaluation_run_id = UUID(baseline_run_id)
    await db_session.commit()

    # New run shows retrieval dropped from 0.85 → 0.65 (0.20 drop > 0.05 delta_max)
    current_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"retrieval_hit_rate": 0.65, "faithfulness_score": 0.83},
    )

    resp = await f302_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": current_run_id},
        headers=_headers(user, org),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["verdict"] == "failed"
    regression_checks = [c for c in body["failed_checks"] if c["metric"].startswith("regression:")]
    assert len(regression_checks) >= 1


@pytest.mark.asyncio
async def test_gate_run_with_baseline_no_regression_passes(
    f302_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()

    baseline_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"retrieval_hit_rate": 0.80, "faithfulness_score": 0.78},
    )

    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Stable Gate",
        description=None,
        thresholds={"regression_delta_max": 0.05},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    from uuid import UUID

    gate.baseline_evaluation_run_id = UUID(baseline_run_id)
    await db_session.commit()

    # Metrics are stable (within delta)
    current_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"retrieval_hit_rate": 0.79, "faithfulness_score": 0.80},
    )

    resp = await f302_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": current_run_id},
        headers=_headers(user, org),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["verdict"] == "passed"
    regression_checks = [c for c in body["failed_checks"] if c["metric"].startswith("regression:")]
    assert len(regression_checks) == 0


# ===========================================================================
# E. Gate report includes baseline_comparison
# ===========================================================================


@pytest.mark.asyncio
async def test_gate_report_has_baseline_comparison(
    f302_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()

    baseline_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"retrieval_hit_rate": 0.85},
    )

    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Report Baseline Gate",
        description=None,
        thresholds={"regression_delta_max": 0.10},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    from uuid import UUID

    gate.baseline_evaluation_run_id = UUID(baseline_run_id)
    await db_session.commit()

    current_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"retrieval_hit_rate": 0.83},
    )

    run_resp = await f302_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": current_run_id},
        headers=_headers(user, org),
    )
    gate_run_id = run_resp.json()["gate_run_id"]

    report_resp = await f302_client.get(
        f"/api/v1/quality-gates/runs/{gate_run_id}/report",
        headers=_headers(user, org),
    )
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert "baseline_comparison" in report
    assert isinstance(report["baseline_comparison"], list)
    assert len(report["baseline_comparison"]) > 0

    rhr = next(
        (d for d in report["baseline_comparison"] if d["metric"] == "retrieval_hit_rate"),
        None,
    )
    assert rhr is not None
    assert rhr["baseline"] == pytest.approx(0.85, abs=1e-4)
    assert rhr["current"] == pytest.approx(0.83, abs=1e-4)


# ===========================================================================
# F. API: refusal_accuracy_score_min threshold enforced via gate run
# ===========================================================================


@pytest.mark.asyncio
async def test_refusal_accuracy_threshold_via_api_fails(
    f302_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()

    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Refusal Gate",
        description=None,
        thresholds={"refusal_accuracy_score_min": 0.90},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"refusal_accuracy_score": 0.65},
    )

    resp = await f302_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["verdict"] == "failed"
    assert any(c["metric"] == "refusal_accuracy_score_min" for c in body["failed_checks"])


@pytest.mark.asyncio
async def test_refusal_accuracy_threshold_via_api_passes(
    f302_client: AsyncClient, db_session: AsyncSession
):
    user, org = await _make_org_user(db_session)
    repo = QualityGateRepository()

    gate = await repo.create_gate(
        db_session,
        organization_id=org.id,
        name="Refusal Gate Pass",
        description=None,
        thresholds={"refusal_accuracy_score_min": 0.85},
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=user.id,
    )
    await db_session.commit()

    eval_run_id = await _seed_eval_run(
        db_session,
        org,
        summary={"refusal_accuracy_score": 0.93},
    )

    resp = await f302_client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        json={"evaluation_run_id": eval_run_id},
        headers=_headers(user, org),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["verdict"] == "passed"


# ===========================================================================
# G. Threshold schema validation
# ===========================================================================


def test_threshold_schema_regression_delta_max_bounds():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        QualityGateThresholds(regression_delta_max=-0.01)

    with pytest.raises(ValidationError):
        QualityGateThresholds(regression_delta_max=1.1)

    # Valid edge values
    t = QualityGateThresholds(regression_delta_max=0.0)
    assert t.regression_delta_max == 0.0
    t2 = QualityGateThresholds(regression_delta_max=1.0)
    assert t2.regression_delta_max == 1.0


def test_threshold_schema_refusal_accuracy_bounds():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        QualityGateThresholds(refusal_accuracy_score_min=1.1)

    t = QualityGateThresholds(refusal_accuracy_score_min=0.80)
    assert t.refusal_accuracy_score_min == pytest.approx(0.80)


def test_threshold_schema_model_dump_excludes_none():
    t = QualityGateThresholds(
        refusal_accuracy_score_min=0.85,
        regression_delta_max=0.05,
    )
    dumped = t.model_dump(exclude_none=True)
    assert "refusal_accuracy_score_min" in dumped
    assert "regression_delta_max" in dumped
    assert "retrieval_hit_rate_min" not in dumped


# ===========================================================================
# H. JUnit XML generation (unit test, no API)
# ===========================================================================


def test_junit_xml_has_failures_for_failed_checks(tmp_path):
    import sys

    sys.path.insert(
        0, str(__import__("pathlib").Path(__file__).parent.parent.parent / "ci" / "scripts")
    )
    from accuracy_eval_runner import _write_junit_xml

    report = {
        "quality_gate_name": "Test Gate",
        "verdict": "failed",
        "eval_mode": "smoke",
        "total_checks": 2,
        "pass_count": 1,
        "fail_count": 1,
        "passed_checks": [
            {
                "metric": "faithfulness_score_min",
                "label": "Faithfulness Score",
                "actual": 0.85,
                "threshold": 0.80,
            }
        ],
        "failed_checks": [
            {
                "metric": "retrieval_hit_rate_min",
                "label": "Retrieval Hit Rate",
                "actual": 0.60,
                "threshold": 0.80,
                "detail": "actual 0.6000 < threshold 0.8000",
            }
        ],
    }

    xml_path = tmp_path / "junit.xml"
    _write_junit_xml(report, xml_path)

    assert xml_path.exists()
    tree = ET.parse(xml_path)
    suite = tree.getroot()
    assert suite.tag == "testsuite"
    assert suite.attrib["failures"] == "1"
    assert suite.attrib["tests"] == "2"

    # Verify failure element present
    failures = [tc.find("failure") for tc in suite.findall("testcase")]
    failure_elements = [f for f in failures if f is not None]
    assert len(failure_elements) == 1
    assert "0.6000 < threshold 0.8000" in (failure_elements[0].text or "")


def test_junit_xml_passed_gate_has_no_failures(tmp_path):
    import sys

    sys.path.insert(
        0, str(__import__("pathlib").Path(__file__).parent.parent.parent / "ci" / "scripts")
    )
    from accuracy_eval_runner import _write_junit_xml

    report = {
        "quality_gate_name": "Passing Gate",
        "verdict": "passed",
        "eval_mode": "nightly",
        "total_checks": 1,
        "pass_count": 1,
        "fail_count": 0,
        "passed_checks": [
            {
                "metric": "retrieval_hit_rate_min",
                "label": "Retrieval Hit Rate",
                "actual": 0.90,
                "threshold": 0.80,
            }
        ],
        "failed_checks": [],
    }

    xml_path = tmp_path / "junit_pass.xml"
    _write_junit_xml(report, xml_path)

    tree = ET.parse(xml_path)
    suite = tree.getroot()
    assert suite.attrib["failures"] == "0"
    failures = [
        tc.find("failure") for tc in suite.findall("testcase") if tc.find("failure") is not None
    ]
    assert failures == []


def test_junit_xml_includes_baseline_comparison_summary(tmp_path):
    import sys

    sys.path.insert(
        0, str(__import__("pathlib").Path(__file__).parent.parent.parent / "ci" / "scripts")
    )
    from accuracy_eval_runner import _write_junit_xml

    report = {
        "quality_gate_name": "Gate",
        "verdict": "passed",
        "eval_mode": "smoke",
        "total_checks": 0,
        "pass_count": 0,
        "fail_count": 0,
        "passed_checks": [],
        "failed_checks": [],
        "baseline_comparison": [
            {
                "metric": "retrieval_hit_rate",
                "label": "Retrieval Hit Rate",
                "baseline": 0.85,
                "current": 0.83,
                "delta": -0.02,
                "regressed": False,
            }
        ],
    }

    xml_path = tmp_path / "junit_baseline.xml"
    _write_junit_xml(report, xml_path)

    tree = ET.parse(xml_path)
    suite = tree.getroot()
    # Baseline summary test case should be present
    names = [tc.attrib.get("name") for tc in suite.findall("testcase")]
    assert any("Baseline" in (n or "") for n in names)
