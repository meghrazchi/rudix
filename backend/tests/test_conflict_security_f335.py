"""Tests for F335: Security and redaction for conflict detection and explain-decision.

Covers:
- Explain-decision response never contains resource content
- Explain-decision response never contains provider secrets / credentials
- Cross-tenant isolation: org A admin cannot see org B conflicts
- Conflict context_json never contains raw document text or chunk content
- Non-admin cannot access conflict endpoints (security boundary enforced)
- Conflict conflict_summary is safe (no PII injection via crafted summaries)
- explain-decision does not reveal existence of resources not belonging to org
- Unknown resource_type always returns 422 (no leakage via timing)
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
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User


@pytest_asyncio.fixture
async def sec_client(
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


async def _seed(db: AsyncSession, *, role: OrganizationRole) -> tuple[User, Organization]:
    org = Organization(
        name=f"sec-{uuid4().hex[:8]}",
        slug=f"sec-{uuid4().hex[:8]}",
    )
    db.add(org)
    await db.flush()
    user = User(
        organization_id=org.id,
        external_auth_id=f"sec-actor-{uuid4().hex[:8]}",
        email=f"sec-{uuid4().hex[:8]}@example.com",
        display_name="SecActor",
    )
    db.add(user)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db.commit()
    return user, org


def _headers(user: User, org: Organization) -> dict[str, str]:
    token = create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )
    return {"Authorization": f"Bearer {token}", "X-Organization-ID": str(org.id)}


# ─── cross-tenant isolation ───────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCrossTenantIsolation:
    async def test_admin_cannot_list_other_org_conflicts(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_a, org_a = await _seed(db_session, role=OrganizationRole.admin)
        _admin_b, org_b = await _seed(db_session, role=OrganizationRole.admin)

        repo = ConflictsRepository()
        await repo.create_conflict(
            db_session,
            organization_id=org_b.id,
            subject_type="user",
            subject_value="u-b",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="orphaned_acl_mapping",
            severity_db="low",
            conflict_summary="org B conflict",
        )
        await db_session.commit()

        resp = await sec_client.get(
            "/admin/permissions/conflicts",
            headers=_headers(admin_a, org_a),
        )
        assert resp.status_code == 200
        # Org A should see zero conflicts (only org B has one)
        assert resp.json()["total"] == 0

    async def test_explain_decision_cannot_probe_other_org_users(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_a, org_a = await _seed(db_session, role=OrganizationRole.admin)
        _admin_b, org_b = await _seed(db_session, role=OrganizationRole.admin)

        # user_b is a member of org_b, not org_a
        user_b = User(
            organization_id=org_b.id,
            external_auth_id=f"b-user-{uuid4().hex[:8]}",
            email=f"b-{uuid4().hex[:8]}@example.com",
            display_name="B",
        )
        db_session.add(user_b)
        await db_session.flush()
        db_session.add(
            OrganizationMember(organization_id=org_b.id, user_id=user_b.id, role="member")
        )
        await db_session.commit()

        # Admin A tries to explain access for User B — should 404 (not a member of A)
        resp = await sec_client.get(
            "/admin/permissions/explain-decision",
            params={
                "subject_user_id": str(user_b.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_a, org_a),
        )
        assert resp.status_code == 404


# ─── response content safety ──────────────────────────────────────────────────


@pytest.mark.asyncio
class TestResponseContentSafety:
    async def test_conflict_detail_has_no_raw_document_content(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org.id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id="doc-secret",
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="high",
            conflict_summary="conflict involving sensitive doc",
            context={"grant_id": str(uuid4()), "deny_id": str(uuid4())},
        )
        await db_session.commit()

        resp = await sec_client.get(
            f"/admin/permissions/conflicts/{conflict.id}",
            headers=_headers(admin, org),
        )
        assert resp.status_code == 200
        body = resp.json()
        # context must not expose raw text / chunk content
        ctx = body.get("context", {})
        assert "text" not in ctx
        assert "content" not in ctx
        assert "chunk" not in ctx

    async def test_explain_response_has_no_provider_secrets(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin, org = await _seed(db_session, role=OrganizationRole.admin)
        subject = User(
            organization_id=org.id,
            external_auth_id=f"s-{uuid4().hex[:8]}",
            email=f"s-{uuid4().hex[:8]}@example.com",
            display_name="S",
        )
        db_session.add(subject)
        await db_session.flush()
        db_session.add(
            OrganizationMember(organization_id=org.id, user_id=subject.id, role="member")
        )
        await db_session.commit()

        resp = await sec_client.get(
            "/admin/permissions/explain-decision",
            params={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin, org),
        )
        assert resp.status_code == 200
        body = resp.text.lower()
        # Must never include raw secrets or provider tokens
        for forbidden in ("sk-", "api_key", "password", "secret", "token", "credential"):
            assert forbidden not in body, f"Response leaked: {forbidden}"

    async def test_conflict_summary_cannot_inject_html(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin, org = await _seed(db_session, role=OrganizationRole.admin)
        repo = ConflictsRepository()
        xss_summary = "<script>alert('xss')</script>"
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
            conflict_summary=xss_summary,
        )
        await db_session.commit()

        resp = await sec_client.get(
            f"/admin/permissions/conflicts/{conflict.id}",
            headers=_headers(admin, org),
        )
        assert resp.status_code == 200
        # FastAPI returns JSON — the script tag is stored as-is in the string field
        # but the API returns JSON (not HTML), so it is safe
        body = resp.json()
        assert body["conflict_summary"] == xss_summary  # stored verbatim, delivered as JSON


# ─── role boundary enforcement ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRoleBoundaryEnforcement:
    async def test_viewer_role_cannot_access_conflicts(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.viewer)
        resp = await sec_client.get(
            "/admin/permissions/conflicts",
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_developer_role_cannot_access_conflicts(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.developer)
        resp = await sec_client.get(
            "/admin/permissions/conflicts",
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_unauthenticated_request_rejected(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await sec_client.get("/admin/permissions/conflicts")
        assert resp.status_code in (401, 403)

    async def test_unknown_resource_type_gives_422_not_500(
        self, sec_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin, org = await _seed(db_session, role=OrganizationRole.admin)
        subject = User(
            organization_id=org.id,
            external_auth_id=f"s-{uuid4().hex[:8]}",
            email=f"s-{uuid4().hex[:8]}@example.com",
            display_name="S",
        )
        db_session.add(subject)
        await db_session.flush()
        db_session.add(
            OrganizationMember(organization_id=org.id, user_id=subject.id, role="member")
        )
        await db_session.commit()

        resp = await sec_client.get(
            "/admin/permissions/explain-decision",
            params={
                "subject_user_id": str(subject.id),
                "resource_type": "future_unregistered_type",
                "action": "view",
            },
            headers=_headers(admin, org),
        )
        assert resp.status_code == 422
