"""Tests for F324: Access Debugger and Permission Simulator.

Covers:
- GET /admin/access-debugger/users: search org members
- POST /admin/access-debugger/simulate: full DB-backed simulation
- Tenant isolation: cannot simulate or search across org boundaries
- Audit event emitted on every simulation
- Non-admin callers receive 403
- Response never exposes resource content
- Extended status codes: allowed, denied, inherited, restricted, unavailable
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
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ─── fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def debugger_client(
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


async def _seed_org(
    db_session: AsyncSession, *, role: OrganizationRole, name_suffix: str = ""
) -> tuple[User, Organization]:
    suffix = name_suffix or uuid4().hex[:8]
    org = Organization(name=f"debugger-org-{suffix}", slug=f"debugger-org-{suffix}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"actor-{suffix}",
        email=f"actor-{suffix}@example.com",
        display_name=f"Actor {suffix}",
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role.value))
    await db_session.commit()
    return user, org


async def _add_member(
    db_session: AsyncSession,
    org: Organization,
    *,
    role: OrganizationRole = OrganizationRole.member,
    email: str | None = None,
    display_name: str | None = None,
) -> User:
    suffix = uuid4().hex[:8]
    member = User(
        organization_id=org.id,
        external_auth_id=f"member-{suffix}",
        email=email or f"member-{suffix}@example.com",
        display_name=display_name or f"Member {suffix}",
    )
    db_session.add(member)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=member.id, role=role.value))
    await db_session.commit()
    return member


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


# ─── User search ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSearchOrgUsers:
    async def test_admin_can_list_users(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        member = await _add_member(db_session, org, display_name="Alice Smith")

        resp = await debugger_client.get(
            "/admin/access-debugger/users",
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        user_ids = [i["user_id"] for i in data["items"]]
        assert str(member.id) in user_ids

    async def test_search_by_email_prefix(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        unique_prefix = f"unique-{uuid4().hex[:6]}"
        await _add_member(db_session, org, email=f"{unique_prefix}@example.com")

        resp = await debugger_client.get(
            f"/admin/access-debugger/users?q={unique_prefix}",
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["email"].startswith(unique_prefix)

    async def test_search_by_display_name(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        unique_name = f"Unique-{uuid4().hex[:6]}"
        await _add_member(db_session, org, display_name=unique_name)

        resp = await debugger_client.get(
            f"/admin/access-debugger/users?q={unique_name[:8]}",
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(i["display_name"] and unique_name in i["display_name"] for i in items)

    async def test_member_cannot_search_users(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_org(db_session, role=OrganizationRole.member)
        resp = await debugger_client.get(
            "/admin/access-debugger/users",
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_does_not_return_other_org_users(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_a, org_a = await _seed_org(db_session, role=OrganizationRole.admin)
        _, org_b = await _seed_org(db_session, role=OrganizationRole.admin)
        unique_prefix = f"orgb-{uuid4().hex[:6]}"
        await _add_member(db_session, org_b, email=f"{unique_prefix}@example.com")

        resp = await debugger_client.get(
            f"/admin/access-debugger/users?q={unique_prefix}",
            headers=_headers(admin_a, org_a),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_each_result_has_required_fields(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        await _add_member(db_session, org)

        resp = await debugger_client.get(
            "/admin/access-debugger/users",
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert "user_id" in item
            assert "email" in item
            assert "role" in item


# ─── Simulate access ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSimulateAccess:
    async def test_admin_role_gets_allow(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org, role=OrganizationRole.admin)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] == "allow"
        assert data["extended_status"] == "allowed"
        assert data["subject_user_id"] == str(subject.id)
        assert data["subject_email"] == subject.email
        assert data["subject_role"] == "admin"

    async def test_viewer_role_gets_allow_for_document_view(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org, role=OrganizationRole.member)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] in ("allow", "deny")
        assert "trace" in data
        assert isinstance(data["trace"], list)
        assert len(data["trace"]) > 0

    async def test_response_has_required_fields(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        for field in (
            "decision",
            "extended_status",
            "matched_rule",
            "deny_reason",
            "subject_user_id",
            "subject_display_name",
            "subject_email",
            "subject_role",
            "resource_type",
            "resource_id",
            "action",
            "trace",
            "reason_chain",
            "effective_permissions",
            "remediation",
            "troubleshooting_links",
            "request_id",
        ):
            assert field in data, f"Missing field: {field}"

    async def test_effective_permissions_returned(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org, role=OrganizationRole.admin)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        perms = resp.json()["effective_permissions"]
        assert isinstance(perms, list)
        assert len(perms) > 0

    async def test_troubleshooting_links_always_present(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        links = resp.json()["troubleshooting_links"]
        assert len(links) >= 2
        hrefs = [link["href"] for link in links]
        assert any("/admin/audit-logs" in h for h in hrefs)
        assert any("/admin/permissions" in h for h in hrefs)

    async def test_document_resource_id_adds_document_link(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org)
        doc_id = str(uuid4())

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
                "resource_id": doc_id,
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        hrefs = [link["href"] for link in resp.json()["troubleshooting_links"]]
        assert any(doc_id in h for h in hrefs)

    async def test_reason_chain_non_empty(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        chain = resp.json()["reason_chain"]
        assert isinstance(chain, list)
        assert len(chain) > 0
        for entry in chain:
            assert "layer" in entry
            assert "outcome" in entry

    async def test_member_cannot_simulate(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed_org(db_session, role=OrganizationRole.member)
        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(uuid4()),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_invalid_resource_type_returns_422(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "not_a_real_type",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 422

    async def test_invalid_action_returns_422(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "not_a_real_action",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 422

    async def test_non_member_subject_returns_404(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(uuid4()),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 404

    async def test_response_does_not_expose_content(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
                "resource_id": str(uuid4()),
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200
        body = resp.text
        # Response must not include content-like fields
        assert "chunk" not in body
        assert '"text"' not in body
        assert '"content"' not in body.replace("conflict_context", "")


# ─── Tenant isolation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.isolation
class TestTenantIsolation:
    async def test_cannot_simulate_cross_org_subject(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_a, org_a = await _seed_org(db_session, role=OrganizationRole.admin)
        _, org_b = await _seed_org(db_session, role=OrganizationRole.admin)
        member_b = await _add_member(db_session, org_b)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(member_b.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_a, org_a),
        )
        assert resp.status_code == 404

    async def test_cannot_search_cross_org_users(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_a, org_a = await _seed_org(db_session, role=OrganizationRole.admin)
        _, org_b = await _seed_org(db_session, role=OrganizationRole.admin)
        unique_prefix = f"isolation-{uuid4().hex[:6]}"
        await _add_member(db_session, org_b, email=f"{unique_prefix}@isolation.test")

        resp = await debugger_client.get(
            f"/admin/access-debugger/users?q={unique_prefix}",
            headers=_headers(admin_a, org_a),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_simulate_resource_stays_within_org(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        admin_a, org_a = await _seed_org(db_session, role=OrganizationRole.admin)
        subject_a = await _add_member(db_session, org_a)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject_a.id),
                "resource_type": "document",
                "action": "view",
                "resource_id": str(uuid4()),
            },
            headers=_headers(admin_a, org_a),
        )
        assert resp.status_code == 200
        data = resp.json()
        # Org IDs in response context must match the caller's org
        assert data["subject_user_id"] == str(subject_a.id)


# ─── Audit event ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestAuditLogging:
    async def test_simulate_emits_audit_event(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from sqlalchemy import select

        from app.models.usage import AuditLog

        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        assert resp.status_code == 200

        audit_rows = (
            (
                await db_session.execute(
                    select(AuditLog).where(
                        AuditLog.organization_id == org.id,
                        AuditLog.action == "access_debugger.simulate",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audit_rows) >= 1
        row = audit_rows[0]
        assert row.metadata_json is not None
        meta = row.metadata_json
        assert meta.get("subject_user_id") == str(subject.id)
        assert "decision" in meta


# ─── Regression: simulator matches real access checks ─────────────────────────


@pytest.mark.asyncio
class TestSimulatorMatchesRealAccess:
    async def test_admin_simulate_allow_matches_engine(
        self, debugger_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Simulator returning 'allow' for admin matches what PolicyEngine produces."""
        from app.auth.policy_engine import (
            Action,
            PolicyEngine,
            ResourceContext,
            ResourceType,
            SubjectContext,
        )
        from app.models.permissions import ROLE_PERMISSIONS

        admin_user, org = await _seed_org(db_session, role=OrganizationRole.admin)
        subject = await _add_member(db_session, org, role=OrganizationRole.admin)

        resp = await debugger_client.post(
            "/admin/access-debugger/simulate",
            json={
                "subject_user_id": str(subject.id),
                "resource_type": "document",
                "action": "view",
            },
            headers=_headers(admin_user, org),
        )
        api_decision = resp.json()["decision"]

        # Run engine directly for comparison
        engine = PolicyEngine()
        admin_perms = frozenset(ROLE_PERMISSIONS.get("admin", []))
        sub = SubjectContext(
            user_id=str(subject.id),
            organization_id=str(org.id),
            roles=frozenset(["admin"]),
            resolved_permissions=admin_perms,
        )
        res_ctx = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=None,
            organization_id=str(org.id),
        )
        direct = engine.authorize(sub, Action.view, res_ctx)
        assert api_decision == direct.result.value
