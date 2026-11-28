"""Service-account access to the CI quality-gate routes.

The CI runner (``ci/scripts/quality_gate_runner.py``) calls three routes with a
``svc_`` token holding the ``quality_gates:run`` scope:

  GET  /evaluations/runs
  POST /quality-gates/{id}/runs
  GET  /quality-gates/runs/{id}/report

Covers the success path, missing scope, cross-organization isolation, routes that stay
human-only, and that a service-account run stores no ``users.id`` foreign key.

Run:
    pytest tests/test_quality_gate_service_account.py -v
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.factory import get_auth_provider
from app.auth.role_or_scope import require_roles_or_token_permissions
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.quality_gates.repositories.quality_gates import QualityGateRepository
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.quality_gate import QualityGate, QualityGateRun
from app.models.usage import AuditLog
from app.models.user import User

_PASSING_SUMMARY = {"retrieval_hit_rate": 0.9, "faithfulness_score": 0.8}
_THRESHOLDS = {"retrieval_hit_rate_min": 0.7, "faithfulness_score_min": 0.6}


@pytest_asyncio.fixture
async def client(
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
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    app.dependency_overrides.clear()


async def _make_admin(db_session: AsyncSession) -> tuple[User, Organization]:
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
    db_session.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=OrganizationRole.admin.value
        )
    )
    await db_session.commit()
    return user, org


def _user_headers(user: User, org: Organization) -> dict[str, str]:
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}


async def _svc_headers(
    client: AsyncClient,
    admin: User,
    org: Organization,
    scopes: list[str],
) -> dict[str, str]:
    """Create a service account through the admin API and return its bearer headers."""
    admin_headers = _user_headers(admin, org)
    account = await client.post(
        "/api/v1/admin/service-accounts",
        headers=admin_headers,
        json={"name": "github-ci", "environment": "ci", "scopes": scopes},
    )
    assert account.status_code == 201, account.text
    token = await client.post(
        f"/api/v1/admin/service-accounts/{account.json()['id']}/tokens",
        headers=admin_headers,
        json={"name": "quality-gate"},
    )
    assert token.status_code == 201, token.text
    return {
        "Authorization": f"Bearer {token.json()['raw_token']}",
        "X-Organization-ID": str(org.id),
    }


async def _seed_gate_and_run(
    db_session: AsyncSession, admin: User, org: Organization
) -> tuple[QualityGate, str, str]:
    """Return (gate, evaluation_set_id, evaluation_run_id) for a passing completed run."""
    gate = await QualityGateRepository().create_gate(
        db_session,
        organization_id=org.id,
        name="Release gate",
        description=None,
        thresholds=_THRESHOLDS,
        baseline_evaluation_run_id=None,
        baseline_safety_run_id=None,
        created_by_id=admin.id,
    )
    eval_repo = EvaluationRepository()
    evset = await eval_repo.create_evaluation_set(
        db_session, organization_id=org.id, name=f"Set-{uuid4().hex[:6]}"
    )
    run = await eval_repo.create_evaluation_run(
        db_session,
        evaluation_set_id=evset.id,
        status="completed",
        config={"metrics_summary": _PASSING_SUMMARY},
    )
    await db_session.commit()
    return gate, str(evset.id), str(run.id)


# ---------------------------------------------------------------------------
# Guard construction
# ---------------------------------------------------------------------------


def test_guard_rejects_empty_token_permissions() -> None:
    with pytest.raises(ValueError):
        require_roles_or_token_permissions(roles=("admin",), token_permissions=())


def test_guard_rejects_empty_roles() -> None:
    with pytest.raises(ValueError):
        require_roles_or_token_permissions(roles=(), token_permissions=("quality_gates:run",))


# ---------------------------------------------------------------------------
# Success path: the full CI runner flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_account_runs_full_ci_flow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, org = await _make_admin(db_session)
    gate, set_id, run_id = await _seed_gate_and_run(db_session, admin, org)
    headers = await _svc_headers(client, admin, org, ["quality_gates:run"])

    listing = await client.get(
        f"/api/v1/evaluations/runs?evaluation_set_id={set_id}&status=completed&limit=50",
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    assert [item["evaluation_run_id"] for item in listing.json()["items"]] == [run_id]

    trigger = await client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        headers=headers,
        json={"evaluation_run_id": run_id},
    )
    assert trigger.status_code == 201, trigger.text
    gate_run_id = trigger.json()["gate_run_id"]
    assert trigger.json()["verdict"] == "passed"

    report = await client.get(f"/api/v1/quality-gates/runs/{gate_run_id}/report", headers=headers)
    assert report.status_code == 200, report.text
    assert report.json()["ci_exit_code"] == 0

    # The service account is not a user: no users.id FK, actor recorded in audit metadata.
    stored = await db_session.get(QualityGateRun, UUID(gate_run_id))
    assert stored is not None
    assert stored.triggered_by_id is None

    audit = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.organization_id == org.id,
                AuditLog.action == "quality_gate.run.completed",
            )
        )
    ).scalar_one()
    assert audit.user_id is None
    assert audit.metadata_json["actor_type"] == "service_account"
    assert audit.metadata_json["service_account_id"]
    assert "raw_token" not in audit.metadata_json


@pytest.mark.asyncio
async def test_admin_user_run_still_records_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, org = await _make_admin(db_session)
    gate, _, run_id = await _seed_gate_and_run(db_session, admin, org)

    trigger = await client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        headers=_user_headers(admin, org),
        json={"evaluation_run_id": run_id},
    )
    assert trigger.status_code == 201, trigger.text
    stored = await db_session.get(QualityGateRun, UUID(trigger.json()["gate_run_id"]))
    assert stored is not None
    assert stored.triggered_by_id == admin.id


# ---------------------------------------------------------------------------
# Missing scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluations_scope_alone_cannot_trigger_or_read_gate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """``evaluations:run`` must not quietly gain gate access."""
    admin, org = await _make_admin(db_session)
    gate, _, run_id = await _seed_gate_and_run(db_session, admin, org)
    headers = await _svc_headers(client, admin, org, ["evaluations:run"])

    trigger = await client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        headers=headers,
        json={"evaluation_run_id": run_id},
    )
    assert trigger.status_code == 403
    assert trigger.json()["detail"] == "Token does not have the required scopes"


@pytest.mark.asyncio
async def test_unrelated_scope_cannot_list_evaluation_runs(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, org = await _make_admin(db_session)
    headers = await _svc_headers(client, admin, org, ["documents:read"])

    listing = await client.get("/api/v1/evaluations/runs", headers=headers)
    assert listing.status_code == 403


# ---------------------------------------------------------------------------
# Cross-organization isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_org_service_account_cannot_reach_gate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin_a, org_a = await _make_admin(db_session)
    gate, set_id, run_id = await _seed_gate_and_run(db_session, admin_a, org_a)
    # Org A's own gate run, created before any org B request: the test shares one DB
    # session across requests, and each request binds it to the caller's tenant.
    own = await client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        headers=_user_headers(admin_a, org_a),
        json={"evaluation_run_id": run_id},
    )
    assert own.status_code == 201, own.text
    gate_run_id = own.json()["gate_run_id"]

    admin_b, org_b = await _make_admin(db_session)
    headers_b = await _svc_headers(client, admin_b, org_b, ["quality_gates:run"])
    # Point the org header at org A: the token's own organization must still win.
    headers_b["X-Organization-ID"] = str(org_a.id)

    trigger = await client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        headers=headers_b,
        json={"evaluation_run_id": run_id},
    )
    assert trigger.status_code == 404

    listing = await client.get(
        f"/api/v1/evaluations/runs?evaluation_set_id={set_id}", headers=headers_b
    )
    assert listing.status_code == 200
    assert listing.json()["items"] == []

    report = await client.get(f"/api/v1/quality-gates/runs/{gate_run_id}/report", headers=headers_b)
    assert report.status_code == 404, report.text


# ---------------------------------------------------------------------------
# Routes that stay human-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_account_cannot_manage_or_override_gates(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    admin, org = await _make_admin(db_session)
    gate, _, _ = await _seed_gate_and_run(db_session, admin, org)
    headers = await _svc_headers(client, admin, org, ["quality_gates:run"])

    create = await client.post(
        "/api/v1/quality-gates",
        headers=headers,
        json={"name": "From CI", "thresholds": _THRESHOLDS},
    )
    assert create.status_code == 403

    delete = await client.delete(f"/api/v1/quality-gates/{gate.id}", headers=headers)
    assert delete.status_code == 403

    failing_set = await EvaluationRepository().create_evaluation_set(
        db_session, organization_id=org.id, name="failing"
    )
    failing_run = await EvaluationRepository().create_evaluation_run(
        db_session,
        evaluation_set_id=failing_set.id,
        status="completed",
        config={"metrics_summary": {"retrieval_hit_rate": 0.1, "faithfulness_score": 0.1}},
    )
    await db_session.commit()
    failed = await client.post(
        f"/api/v1/quality-gates/{gate.id}/runs",
        headers=headers,
        json={"evaluation_run_id": str(failing_run.id)},
    )
    assert failed.status_code == 201
    assert failed.json()["verdict"] == "failed"

    override = await client.post(
        f"/api/v1/quality-gates/runs/{failed.json()['gate_run_id']}/override",
        headers=headers,
        json={"reason": "CI should never be able to override its own failed gate."},
    )
    assert override.status_code == 403
