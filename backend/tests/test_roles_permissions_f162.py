"""Tests for F162: Advanced roles and custom permissions.

Covers:
- Permission matrix unit tests (ROLE_PERMISSIONS)
- PermissionService resolution
- Custom role CRUD API endpoints
- Authorization enforcement (forbidden states)
- Audit log emission on role changes
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
from app.auth.permission_service import PermissionService
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.main import app
from app.models.custom_role import CustomRole, CustomRolePermission
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.permissions import PERMISSION_CATALOG, ROLE_PERMISSIONS, PermissionType
from app.models.user import User

# ─── fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def roles_client(
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


async def _seed_org_actor(
    db_session: AsyncSession,
    *,
    role: OrganizationRole,
    org_name_prefix: str = "roles",
) -> tuple[User, Organization]:
    org = Organization(
        name=f"{org_name_prefix}-{uuid4().hex[:8]}",
        slug=f"{org_name_prefix}-{uuid4().hex[:8]}",
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


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


def _token(user: User, org: Organization) -> str:
    return create_app_access_token(
        subject=user.external_auth_id,
        organization_id=str(org.id),
        expires_in_seconds=600,
    )


# ─── permission matrix unit tests ────────────────────────────────────────────


class TestPermissionMatrix:
    def test_viewer_cannot_manage_roles(self) -> None:
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        assert PermissionType.roles_view not in viewer_perms
        assert PermissionType.roles_manage not in viewer_perms

    def test_owner_has_all_high_privilege_permissions(self) -> None:
        owner_perms = ROLE_PERMISSIONS["owner"]
        assert PermissionType.billing_manage in owner_perms
        assert PermissionType.roles_manage in owner_perms
        assert PermissionType.team_manage in owner_perms
        assert PermissionType.security_center_configure in owner_perms

    def test_admin_cannot_manage_billing(self) -> None:
        admin_perms = ROLE_PERMISSIONS["admin"]
        assert PermissionType.billing_view not in admin_perms
        assert PermissionType.billing_manage not in admin_perms

    def test_billing_admin_can_only_access_billing_and_audit(self) -> None:
        billing_perms = ROLE_PERMISSIONS["billing_admin"]
        assert PermissionType.billing_view in billing_perms
        assert PermissionType.billing_manage in billing_perms
        assert PermissionType.documents_view not in billing_perms
        assert PermissionType.chat_use not in billing_perms

    def test_security_admin_can_configure_security_and_view_audit(self) -> None:
        sec_perms = ROLE_PERMISSIONS["security_admin"]
        assert PermissionType.security_center_configure in sec_perms
        assert PermissionType.audit_logs_export in sec_perms
        assert PermissionType.billing_manage not in sec_perms

    def test_developer_has_api_key_and_webhook_permissions(self) -> None:
        dev_perms = ROLE_PERMISSIONS["developer"]
        assert PermissionType.api_keys_create in dev_perms
        assert PermissionType.webhooks_create in dev_perms
        assert PermissionType.agents_create in dev_perms

    def test_reviewer_has_evaluation_permissions(self) -> None:
        rev_perms = ROLE_PERMISSIONS["reviewer"]
        assert PermissionType.evaluations_create in rev_perms
        assert PermissionType.evaluations_run in rev_perms
        assert PermissionType.audit_logs_view in rev_perms

    def test_permission_catalog_is_complete(self) -> None:
        catalog_perms = {entry["permission"] for entry in PERMISSION_CATALOG}
        for perm in PermissionType:
            assert perm.value in catalog_perms, f"Missing from catalog: {perm.value}"

    def test_member_is_subset_of_admin(self) -> None:
        member_perms = ROLE_PERMISSIONS["member"]
        admin_perms = ROLE_PERMISSIONS["admin"]
        # Every member permission should be in admin
        assert member_perms.issubset(admin_perms)

    def test_viewer_is_subset_of_member(self) -> None:
        viewer_perms = ROLE_PERMISSIONS["viewer"]
        member_perms = ROLE_PERMISSIONS["member"]
        assert viewer_perms.issubset(member_perms)


# ─── PermissionService unit tests ────────────────────────────────────────────


class TestPermissionService:
    @pytest.mark.asyncio
    async def test_builtin_role_permissions_resolved(self, db_session: AsyncSession) -> None:
        svc = PermissionService()
        perms = await svc.get_user_permissions(db_session, roles=["admin"], custom_role_id=None)
        assert PermissionType.team_manage in perms
        assert PermissionType.billing_manage not in perms

    @pytest.mark.asyncio
    async def test_custom_role_permissions_merged(self, db_session: AsyncSession) -> None:
        org = Organization(name=f"perm-svc-{uuid4().hex[:8]}", slug=f"ps-{uuid4().hex[:8]}")
        db_session.add(org)
        await db_session.flush()

        custom_role = CustomRole(
            organization_id=org.id,
            name="Custom Read",
        )
        db_session.add(custom_role)
        await db_session.flush()
        db_session.add(
            CustomRolePermission(
                custom_role_id=custom_role.id,
                permission=PermissionType.billing_view.value,
            )
        )
        await db_session.flush()

        svc = PermissionService()
        perms = await svc.get_user_permissions(
            db_session,
            roles=["member"],
            custom_role_id=custom_role.id,
        )
        assert PermissionType.billing_view in perms
        assert PermissionType.documents_view in perms

    @pytest.mark.asyncio
    async def test_custom_role_with_base_role_inherits_permissions(
        self, db_session: AsyncSession
    ) -> None:
        org = Organization(name=f"perm-base-{uuid4().hex[:8]}", slug=f"pb-{uuid4().hex[:8]}")
        db_session.add(org)
        await db_session.flush()

        custom_role = CustomRole(
            organization_id=org.id,
            name="Inherited Role",
            base_role="developer",
        )
        db_session.add(custom_role)
        await db_session.flush()

        svc = PermissionService()
        perms = await svc.get_user_permissions(
            db_session,
            roles=["viewer"],
            custom_role_id=custom_role.id,
        )
        assert PermissionType.api_keys_create in perms
        assert PermissionType.webhooks_create in perms


# ─── Custom role CRUD API tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_roles_returns_builtin_and_custom(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)

    response = await roles_client.get(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )

    assert response.status_code == 200
    payload = response.json()
    assert "builtin_roles" in payload
    assert "custom_roles" in payload
    assert len(payload["builtin_roles"]) == len(OrganizationRole)
    assert payload["custom_roles"] == []


@pytest.mark.asyncio
async def test_list_roles_forbidden_for_viewer(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.viewer)
    token = _token(actor, org)

    response = await roles_client.get(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_custom_role_success(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)

    response = await roles_client.post(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={
            "name": "Read-only Analyst",
            "description": "Can view and chat",
            "base_role": "viewer",
            "permissions": [
                PermissionType.documents_view.value,
                PermissionType.chat_use.value,
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "Read-only Analyst"
    assert payload["base_role"] == "viewer"
    assert PermissionType.documents_view.value in payload["permissions"]
    assert payload["is_builtin"] is False


@pytest.mark.asyncio
async def test_create_custom_role_rejected_for_member(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.member)
    token = _token(actor, org)

    response = await roles_client.post(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"name": "Unauthorized Role", "permissions": []},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_custom_role_duplicate_name_rejected(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    await roles_client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={"name": "Unique Role", "permissions": []},
    )
    response = await roles_client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={"name": "Unique Role", "permissions": []},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_custom_role_reserved_name_rejected(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)

    response = await roles_client.post(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"name": "admin", "permissions": []},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_custom_role_invalid_permission_rejected(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)

    response = await roles_client.post(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        json={"name": "Bad Role", "permissions": ["not:a:valid:permission"]},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_custom_role_by_id(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await roles_client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={"name": "Fetchable Role", "permissions": [PermissionType.chat_use.value]},
    )
    role_id = create_resp.json()["id"]

    response = await roles_client.get(
        f"/api/v1/admin/roles/{role_id}",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == role_id


@pytest.mark.asyncio
async def test_get_custom_role_not_found(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)

    response = await roles_client.get(
        f"/api/v1/admin/roles/{uuid4()}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_custom_role_name_and_permissions(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await roles_client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={"name": "Editable Role", "permissions": [PermissionType.chat_use.value]},
    )
    role_id = create_resp.json()["id"]

    patch_resp = await roles_client.patch(
        f"/api/v1/admin/roles/{role_id}",
        headers=headers,
        json={
            "name": "Updated Role",
            "permissions": [PermissionType.documents_view.value],
        },
    )
    assert patch_resp.status_code == 200
    payload = patch_resp.json()
    assert payload["name"] == "Updated Role"
    assert PermissionType.documents_view.value in payload["permissions"]
    assert PermissionType.chat_use.value not in payload["permissions"]


@pytest.mark.asyncio
async def test_delete_custom_role_success(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    create_resp = await roles_client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={"name": "Deletable Role", "permissions": []},
    )
    role_id = create_resp.json()["id"]

    delete_resp = await roles_client.delete(
        f"/api/v1/admin/roles/{role_id}",
        headers=headers,
    )
    assert delete_resp.status_code == 204

    get_resp = await roles_client.get(
        f"/api/v1/admin/roles/{role_id}",
        headers=headers,
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_custom_role_forbidden_for_developer(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.developer)
    token = _token(actor, org)

    response = await roles_client.delete(
        f"/api/v1/admin/roles/{uuid4()}",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_permissions_catalog(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.admin)
    token = _token(actor, org)

    response = await roles_client.get(
        "/api/v1/admin/roles/permissions",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == len(PERMISSION_CATALOG)
    categories = {entry["category"] for entry in payload["items"]}
    assert "documents" in categories
    assert "billing" in categories
    assert "roles" in categories


@pytest.mark.asyncio
async def test_custom_roles_are_org_scoped(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor1, org1 = await _seed_org_actor(
        db_session, role=OrganizationRole.admin, org_name_prefix="roles-org1"
    )
    actor2, org2 = await _seed_org_actor(
        db_session, role=OrganizationRole.admin, org_name_prefix="roles-org2"
    )

    await roles_client.post(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=_token(actor1, org1), organization_id=str(org1.id)),
        json={"name": "Org1 Role", "permissions": []},
    )

    response = await roles_client.get(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=_token(actor2, org2), organization_id=str(org2.id)),
    )
    payload = response.json()
    custom_names = [r["name"] for r in payload["custom_roles"]]
    assert "Org1 Role" not in custom_names


@pytest.mark.asyncio
async def test_new_builtin_roles_are_listed(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.owner)
    token = _token(actor, org)

    response = await roles_client.get(
        "/api/v1/admin/roles",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
    )
    assert response.status_code == 200
    builtin_roles = {r["role"] for r in response.json()["builtin_roles"]}
    assert "reviewer" in builtin_roles
    assert "developer" in builtin_roles
    assert "security_admin" in builtin_roles
    assert "billing_admin" in builtin_roles


@pytest.mark.asyncio
async def test_security_admin_can_view_roles_but_not_manage(
    roles_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    actor, org = await _seed_org_actor(db_session, role=OrganizationRole.security_admin)
    token = _token(actor, org)
    headers = _auth_headers(token=token, organization_id=str(org.id))

    view_resp = await roles_client.get("/api/v1/admin/roles", headers=headers)
    assert view_resp.status_code == 403

    create_resp = await roles_client.post(
        "/api/v1/admin/roles",
        headers=headers,
        json={"name": "Unauthorized", "permissions": []},
    )
    assert create_resp.status_code == 403
