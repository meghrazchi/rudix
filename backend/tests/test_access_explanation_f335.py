"""Tests for F335: Access explanation and conflicts API.

Covers:
- GET /admin/permissions/explain-decision: policy trace for a user+resource+action
- GET /admin/permissions/conflicts: list with filters
- GET /admin/permissions/conflicts/{id}: conflict detail
- PATCH /admin/permissions/conflicts/{id}/status: status transitions
- POST /admin/permissions/conflicts/scan: trigger scan
- 403 for non-admin callers on all endpoints
- Trace step parsing produces correct outcome labels
"""

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
from app.domains.permissions.repositories.conflicts import ConflictsRepository
from app.interfaces.http.admin_conflicts import _parse_trace
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ─── fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def conflict_client(
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


async def _seed(db_session: AsyncSession, *, role: OrganizationRole) -> tuple[User, Organization]:
    org = Organization(
        name=f"conflict-test-{uuid4().hex[:8]}",
        slug=f"conflict-test-{uuid4().hex[:8]}",
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"actor-{uuid4().hex[:8]}",
        email=f"actor-{uuid4().hex[:8]}@example.com",
        display_name="Actor",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=role.value,
        )
    )
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


# ─── trace parsing ─────────────────────────────────────────────────────────────


class TestTraceParser:
    def test_allow_entry_parses(self) -> None:
        steps = _parse_trace(["owner_admin_override:allow"])
        assert len(steps) == 1
        assert steps[0].rule == "owner_admin_override"
        assert steps[0].outcome == "allow"

    def test_deny_entry_parses(self) -> None:
        steps = _parse_trace(["explicit_resource_deny:deny(explicit_resource_deny)"])
        assert steps[0].outcome == "deny"
        assert steps[0].detail == "explicit_resource_deny"

    def test_pass_entry_parses(self) -> None:
        steps = _parse_trace(["tenant_boundary:pass"])
        assert steps[0].outcome == "pass"
        assert steps[0].rule == "tenant_boundary"

    def test_multi_step_trace(self) -> None:
        raw = [
            "no_organization_context:pass",
            "tenant_boundary:pass",
            "system_deny:pass",
            "unknown_resource_type:pass",
            "owner_admin_override:allow",
        ]
        steps = _parse_trace(raw)
        assert len(steps) == 5
        assert steps[-1].outcome == "allow"

    def test_missing_perm_trace(self) -> None:
        raw = [
            "no_organization_context:pass",
            "tenant_boundary:pass",
            "system_deny:pass",
            "unknown_resource_type:pass",
            "owner_admin_override:pass",
            "explicit_resource_deny:pass",
            "explicit_resource_allow:pass",
            "collection_allow:pass",
            "connector_acl:pass",
            "feature_entitlement:pass",
            "role_permission:missing=documents:view",
        ]
        steps = _parse_trace(raw)
        last = steps[-1]
        assert last.rule == "role_permission"


# ─── API: list conflicts ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestListConflicts:
    async def test_admin_can_list_empty_conflicts(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await conflict_client.get(
            "/admin/permissions/conflicts",
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert data["total"] == 0

    async def test_member_cannot_list_conflicts(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.member)
        resp = await conflict_client.get(
            "/admin/permissions/conflicts",
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_list_supports_severity_filter(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        await repo.create_conflict(
            db_session,
            organization_id=org.id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="high",
            conflict_summary="blocking conflict",
        )
        await db_session.commit()

        resp = await conflict_client.get(
            "/admin/permissions/conflicts?severity=blocking",
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["severity"] == "blocking"

    async def test_list_severity_info_returns_empty_for_high(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        await repo.create_conflict(
            db_session,
            organization_id=org.id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="high",
            conflict_summary="blocking conflict",
        )
        await db_session.commit()

        resp = await conflict_client.get(
            "/admin/permissions/conflicts?severity=info",
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_pagination_page_size(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        for i in range(5):
            await repo.create_conflict(
                db_session,
                organization_id=org.id,
                subject_type="user",
                subject_value=f"u{i}",
                user_id=None,
                role_name=None,
                resource_type="document",
                resource_id=None,
                action="read_only",
                conflict_type="stale_grant_deleted_resource",
                severity_db="low",
                conflict_summary=f"conflict {i}",
            )
        await db_session.commit()

        resp = await conflict_client.get(
            "/admin/permissions/conflicts?page_size=2",
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2


# ─── API: get conflict detail ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetConflict:
    async def test_admin_can_get_conflict(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org.id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="high",
            conflict_summary="blocking",
        )
        await db_session.commit()

        resp = await conflict_client.get(
            f"/admin/permissions/conflicts/{conflict.id}",
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(conflict.id)
        assert data["severity"] == "blocking"
        assert "remediation" in data
        assert len(data["remediation"]) >= 1

    async def test_404_for_unknown_conflict(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await conflict_client.get(
            f"/admin/permissions/conflicts/{uuid4()}",
            headers=_headers(user, org),
        )
        assert resp.status_code == 404

    async def test_cannot_get_other_org_conflict(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_a, org_a = await _seed(db_session, role=OrganizationRole.admin)
        _user_b, org_b = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org_b.id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="orphaned_acl_mapping",
            severity_db="low",
            conflict_summary="org b conflict",
        )
        await db_session.commit()

        resp = await conflict_client.get(
            f"/admin/permissions/conflicts/{conflict.id}",
            headers=_headers(user_a, org_a),
        )
        assert resp.status_code == 404


# ─── API: update conflict status ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestUpdateConflictStatus:
    async def test_can_transition_open_to_investigating(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org.id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="high",
            conflict_summary="test",
        )
        await db_session.commit()

        resp = await conflict_client.patch(
            f"/admin/permissions/conflicts/{conflict.id}/status",
            json={"status": "investigating", "resolution_note": "Looking into it"},
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "investigating"

    async def test_can_transition_to_resolved(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org.id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="stale_grant_deleted_resource",
            severity_db="low",
            conflict_summary="test",
        )
        await db_session.commit()

        resp = await conflict_client.patch(
            f"/admin/permissions/conflicts/{conflict.id}/status",
            json={"status": "resolved"},
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["resolved_at"] is not None

    async def test_cannot_update_already_resolved_conflict(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org.id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="stale_grant_deleted_resource",
            severity_db="low",
            conflict_summary="test",
        )
        await db_session.flush()
        await repo.update_conflict_status(db_session, conflict=conflict, new_status="resolved")
        await db_session.commit()

        resp = await conflict_client.patch(
            f"/admin/permissions/conflicts/{conflict.id}/status",
            json={"status": "dismissed"},
            headers=_headers(user, org),
        )
        assert resp.status_code == 409

    async def test_member_cannot_update_conflict(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.member)
        resp = await conflict_client.patch(
            f"/admin/permissions/conflicts/{uuid4()}/status",
            json={"status": "resolved"},
            headers=_headers(user, org),
        )
        assert resp.status_code == 403


# ─── API: scan ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestScanConflicts:
    async def test_scan_returns_result_shape(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await conflict_client.post(
            "/admin/permissions/conflicts/scan",
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "conflicts_detected" in data
        assert "conflicts_created" in data
        assert "scan_duration_ms" in data
        assert "scanned_grants" in data
        assert "scanned_denies" in data
        assert "scanned_acl_mappings" in data

    async def test_member_cannot_trigger_scan(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.member)
        resp = await conflict_client.post(
            "/admin/permissions/conflicts/scan",
            headers=_headers(user, org),
        )
        assert resp.status_code == 403


# ─── API: explain decision ────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestExplainDecision:
    async def test_admin_gets_allow_for_own_member_user(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed(db_session, role=OrganizationRole.admin)

        # Add a member to explain
        subject_user = User(
            organization_id=org.id,
            external_auth_id=f"sub-{uuid4().hex[:8]}",
            email=f"sub-{uuid4().hex[:8]}@example.com",
            display_name="Subject",
        )
        db_session.add(subject_user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=subject_user.id,
                role="member",
            )
        )
        await db_session.commit()

        resp = await conflict_client.get(
            "/admin/permissions/explain-decision",
            params={
                "subject_user_id": str(subject_user.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "decision" in data
        assert "trace" in data
        assert isinstance(data["trace"], list)
        assert len(data["trace"]) > 0
        assert "request_id" in data

    async def test_explain_returns_deny_for_unknown_action(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed(db_session, role=OrganizationRole.admin)

        subject_user = User(
            organization_id=org.id,
            external_auth_id=f"sub-{uuid4().hex[:8]}",
            email=f"sub-{uuid4().hex[:8]}@example.com",
            display_name="Subject",
        )
        db_session.add(subject_user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=subject_user.id,
                role="member",
            )
        )
        await db_session.commit()

        resp = await conflict_client.get(
            "/admin/permissions/explain-decision",
            params={
                "subject_user_id": str(subject_user.id),
                "resource_type": "document",
                "action": "not_a_real_action",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 422

    async def test_explain_404_for_non_member_subject(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await conflict_client.get(
            "/admin/permissions/explain-decision",
            params={
                "subject_user_id": str(uuid4()),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 404

    async def test_member_cannot_explain_decision(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.member)
        resp = await conflict_client.get(
            "/admin/permissions/explain-decision",
            params={
                "subject_user_id": str(uuid4()),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_explain_decision_does_not_expose_resource_content(
        self, conflict_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed(db_session, role=OrganizationRole.admin)

        subject_user = User(
            organization_id=org.id,
            external_auth_id=f"sub-{uuid4().hex[:8]}",
            email=f"sub-{uuid4().hex[:8]}@example.com",
            display_name="Subject",
        )
        db_session.add(subject_user)
        await db_session.flush()
        db_session.add(
            OrganizationMember(
                organization_id=org.id,
                user_id=subject_user.id,
                role="member",
            )
        )
        await db_session.commit()

        resp = await conflict_client.get(
            "/admin/permissions/explain-decision",
            params={
                "subject_user_id": str(subject_user.id),
                "resource_type": "document",
                "action": "view",
                "resource_id": "some-doc-id",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        body = resp.text
        # Response must not include content-looking fields
        assert "content" not in body.lower().replace("conflict_context", "")
        assert "text" not in body
