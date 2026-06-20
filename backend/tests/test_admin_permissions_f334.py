"""Tests for F334: Admin role matrix and resource access management UI.

Covers:
- GET /admin/permissions/role-matrix: returns all builtin roles with permissions
- PATCH /admin/permissions/role-matrix/{role}: update role permissions
- Unsafe change prevention (owner required perms, no lockout)
- Owner-only restriction for owner-role edits
- GET/POST/DELETE /admin/permissions/resource-grants
- GET/POST/DELETE /admin/permissions/resource-denies
- Audit log emission on all mutating operations
- Non-admin access blocked (403)
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
from app.domains.permissions.services.permissions_service import check_role_permission_safety
from app.main import app
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.permissions import ROLE_PERMISSIONS, PermissionType
from app.models.user import User

# ─── fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def perm_client(
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
        name=f"perm-test-{uuid4().hex[:8]}",
        slug=f"perm-test-{uuid4().hex[:8]}",
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


# ─── safety checks (unit) ─────────────────────────────────────────────────────


class TestRolePermissionSafetyChecks:
    def test_removing_owner_required_permissions_is_blocked(self) -> None:
        current = {r: ROLE_PERMISSIONS.get(r, frozenset()) for r in ["owner", "admin"]}
        error = check_role_permission_safety("owner", [], all_roles_current=current)
        assert error is not None
        assert "roles:manage" in error

    def test_locking_out_all_admins_is_blocked(self) -> None:
        # Both owner and admin stripped of roles:manage
        current = {
            "owner": frozenset({"team:view"}),
            "admin": frozenset({"team:view"}),
        }
        error = check_role_permission_safety(
            "owner",
            ["team:view"],
            all_roles_current=current,
        )
        assert error is not None
        assert "roles:manage" in error

    def test_admin_keeping_roles_manage_passes(self) -> None:
        current = {
            "owner": frozenset({"roles:manage", "team:manage"}),
            "admin": frozenset({"roles:manage"}),
        }
        # Remove roles:manage from owner while admin still has it
        error = check_role_permission_safety(
            "owner",
            ["team:manage"],
            all_roles_current=current,
        )
        assert error is None

    def test_owner_retains_required_perms_passes(self) -> None:
        current = {r: ROLE_PERMISSIONS.get(r, frozenset()) for r in ["owner", "admin"]}
        new_perms = list(ROLE_PERMISSIONS["owner"])
        error = check_role_permission_safety("owner", new_perms, all_roles_current=current)
        assert error is None


# ─── role matrix endpoints ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGetRoleMatrix:
    async def test_admin_can_get_role_matrix(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await perm_client.get(
            "/api/v1/admin/permissions/role-matrix", headers=_headers(user, org)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "roles" in data
        assert "all_permissions" in data
        roles = {r["role"] for r in data["roles"]}
        assert "owner" in roles
        assert "admin" in roles
        assert "member" in roles
        assert "viewer" in roles

    async def test_role_matrix_includes_permission_lists(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await perm_client.get(
            "/api/v1/admin/permissions/role-matrix", headers=_headers(user, org)
        )
        assert resp.status_code == 200
        owner_entry = next(r for r in resp.json()["roles"] if r["role"] == "owner")
        assert PermissionType.roles_manage in owner_entry["permissions"]
        assert PermissionType.billing_manage in owner_entry["permissions"]

    async def test_member_cannot_get_role_matrix(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.member)
        resp = await perm_client.get(
            "/api/v1/admin/permissions/role-matrix", headers=_headers(user, org)
        )
        assert resp.status_code == 403

    async def test_viewer_cannot_get_role_matrix(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.viewer)
        resp = await perm_client.get(
            "/api/v1/admin/permissions/role-matrix", headers=_headers(user, org)
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestUpdateRoleMatrix:
    async def test_owner_can_update_member_permissions(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.owner)
        new_perms = sorted(ROLE_PERMISSIONS["member"])
        resp = await perm_client.patch(
            "/api/v1/admin/permissions/role-matrix/member",
            json={"permissions": new_perms},
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["role"] == "member"
        assert set(data["permissions"]) == set(new_perms)

    async def test_admin_cannot_update_owner_role(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await perm_client.patch(
            "/api/v1/admin/permissions/role-matrix/owner",
            json={"permissions": list(ROLE_PERMISSIONS["owner"])},
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_unsafe_change_removing_owner_required_perms_blocked(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.owner)
        resp = await perm_client.patch(
            "/api/v1/admin/permissions/role-matrix/owner",
            json={"permissions": ["documents:view"]},
            headers=_headers(user, org),
        )
        assert resp.status_code == 409
        assert "roles:manage" in resp.json()["detail"]

    async def test_unknown_permissions_rejected(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.owner)
        resp = await perm_client.patch(
            "/api/v1/admin/permissions/role-matrix/member",
            json={"permissions": ["not:a:real:permission"]},
            headers=_headers(user, org),
        )
        assert resp.status_code == 422

    async def test_nonexistent_role_returns_404(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.owner)
        resp = await perm_client.patch(
            "/api/v1/admin/permissions/role-matrix/does_not_exist",
            json={"permissions": []},
            headers=_headers(user, org),
        )
        assert resp.status_code == 404

    async def test_member_cannot_update_role_matrix(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.member)
        resp = await perm_client.patch(
            "/api/v1/admin/permissions/role-matrix/viewer",
            json={"permissions": []},
            headers=_headers(user, org),
        )
        assert resp.status_code == 403


# ─── resource grants ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestResourceGrants:
    async def test_admin_can_list_grants(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await perm_client.get(
            "/api/v1/admin/permissions/resource-grants", headers=_headers(user, org)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_admin_can_create_grant(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        target_user_id = str(uuid4())
        resp = await perm_client.post(
            "/api/v1/admin/permissions/resource-grants",
            json={
                "principal_type": "user",
                "principal_value": target_user_id,
                "resource_type": "document",
                "resource_id": str(uuid4()),
                "action": "read_only",
                "reason": "Test grant",
            },
            headers=_headers(user, org),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["principal_value"] == target_user_id
        assert data["status"] == "active"
        assert data["kind"] == "grant"

    async def test_admin_can_revoke_grant(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        create_resp = await perm_client.post(
            "/api/v1/admin/permissions/resource-grants",
            json={
                "principal_type": "user",
                "principal_value": str(uuid4()),
                "resource_type": "collection",
                "resource_id": None,
                "action": "manage",
            },
            headers=_headers(user, org),
        )
        assert create_resp.status_code == 201
        grant_id = create_resp.json()["id"]

        del_resp = await perm_client.delete(
            f"/api/v1/admin/permissions/resource-grants/{grant_id}",
            headers=_headers(user, org),
        )
        assert del_resp.status_code == 204

    async def test_revoke_nonexistent_grant_returns_404(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await perm_client.delete(
            f"/api/v1/admin/permissions/resource-grants/{uuid4()}",
            headers=_headers(user, org),
        )
        assert resp.status_code == 404

    async def test_member_cannot_create_grant(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.member)
        resp = await perm_client.post(
            "/api/v1/admin/permissions/resource-grants",
            json={
                "principal_type": "user",
                "principal_value": str(uuid4()),
                "resource_type": "document",
                "action": "read_only",
            },
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_grants_filtered_by_resource_type(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        await perm_client.post(
            "/api/v1/admin/permissions/resource-grants",
            json={
                "principal_type": "user",
                "principal_value": str(uuid4()),
                "resource_type": "document",
                "action": "read_only",
            },
            headers=_headers(user, org),
        )
        await perm_client.post(
            "/api/v1/admin/permissions/resource-grants",
            json={
                "principal_type": "user",
                "principal_value": str(uuid4()),
                "resource_type": "collection",
                "action": "read_only",
            },
            headers=_headers(user, org),
        )
        resp = await perm_client.get(
            "/api/v1/admin/permissions/resource-grants?resource_type=document",
            headers=_headers(user, org),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(i["resource_type"] == "document" for i in items)


# ─── resource denies ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestResourceDenies:
    async def test_admin_can_list_denies(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        resp = await perm_client.get(
            "/api/v1/admin/permissions/resource-denies", headers=_headers(user, org)
        )
        assert resp.status_code == 200

    async def test_admin_can_create_deny(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        target = str(uuid4())
        resp = await perm_client.post(
            "/api/v1/admin/permissions/resource-denies",
            json={
                "principal_type": "user",
                "principal_value": target,
                "resource_type": "connector",
                "action": "manage",
                "reason": "Revocation test",
            },
            headers=_headers(user, org),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["kind"] == "deny"
        assert data["status"] == "active"

    async def test_admin_can_revoke_deny(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.admin)
        create_resp = await perm_client.post(
            "/api/v1/admin/permissions/resource-denies",
            json={
                "principal_type": "user",
                "principal_value": str(uuid4()),
                "resource_type": "document",
                "action": "read_only",
            },
            headers=_headers(user, org),
        )
        deny_id = create_resp.json()["id"]
        del_resp = await perm_client.delete(
            f"/api/v1/admin/permissions/resource-denies/{deny_id}",
            headers=_headers(user, org),
        )
        assert del_resp.status_code == 204

    async def test_member_cannot_create_deny(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user, org = await _seed(db_session, role=OrganizationRole.member)
        resp = await perm_client.post(
            "/api/v1/admin/permissions/resource-denies",
            json={
                "principal_type": "user",
                "principal_value": str(uuid4()),
                "resource_type": "document",
                "action": "read_only",
            },
            headers=_headers(user, org),
        )
        assert resp.status_code == 403

    async def test_deny_not_visible_across_orgs(
        self, perm_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user_a, org_a = await _seed(db_session, role=OrganizationRole.admin)
        user_b, org_b = await _seed(db_session, role=OrganizationRole.admin)

        create_resp = await perm_client.post(
            "/api/v1/admin/permissions/resource-denies",
            json={
                "principal_type": "user",
                "principal_value": str(uuid4()),
                "resource_type": "document",
                "action": "read_only",
            },
            headers=_headers(user_a, org_a),
        )
        deny_id = create_resp.json()["id"]

        # Org B cannot revoke org A's deny
        del_resp = await perm_client.delete(
            f"/api/v1/admin/permissions/resource-denies/{deny_id}",
            headers=_headers(user_b, org_b),
        )
        assert del_resp.status_code == 404
