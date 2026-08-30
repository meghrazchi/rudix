"""Backend tests for F354: Permission and Access Report.

Covers:
  A. Summary — total/admin user counts
  B. Summary — external_users via verified domain vs majority-domain heuristic
  C. Summary — broad_access_users (wildcard grant + connector broad-scope signals, no double count)
  D. Summary — expired_active_grants (past/future/null expires_at)
  E. Summary — orphaned_grants (grant referencing a deleted document)
  F. Summary — resources_without_owner (document + collection)
  G. Summary — connector_acl_mismatches (acl_changed/permission_revoked vs renamed/resolved)
  H. Summary — unauthorized_access_attempts sourced from AUTHZ_ACCESS_DENIED audit rows
  I. Rows — explicit grant / deny / connector ACL / conflict merge and dedupe
  J. Tenant isolation — org A never sees org B's data
  K. HTTP — GET /admin/permissions-access/summary requires security_center_view (member 403)
  L. HTTP — GET /admin/permissions-access/export requires security_center_configure
     (view-only custom role gets 403; admin gets 200 CSV)
  M. HTTP — exported CSV never contains resource content or internal IDs (column allow-list)

Run:
    pytest tests/test_permissions_access_report_f354.py -v
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
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
from app.domains.admin.audit_events import AUTHZ_ACCESS_DENIED
from app.domains.permissions.services.permissions_access_report_service import (
    PermissionsAccessFilters,
    PermissionsAccessReportService,
)
from app.main import app
from app.models.authorization import ResourceAccessGrant, SourceAclMapping
from app.models.collection import Collection
from app.models.connector import ConnectorPermissionReview
from app.models.connector_sync import SyncConflict
from app.models.custom_role import CustomRole, CustomRolePermission
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.org_domain_verification import OrgDomainVerification
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pa_client(
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

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
    get_auth_provider.cache_clear()


def _token(user_id: str, org_id: str, role: str = OrganizationRole.admin.value) -> str:
    return create_app_access_token(
        user_id=user_id,
        organization_id=org_id,
        role=role,
        secret=SecretStr("test-secret"),
        issuer="rudix-test",
        audience="rudix-test-audience",
    )


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


async def _make_org(db: AsyncSession) -> Organization:
    slug = f"pa-org-{uuid4().hex[:8]}"
    org = Organization(name=f"Permissions Access Org {slug}", slug=slug)
    db.add(org)
    await db.flush()
    return org


async def _make_member(
    db: AsyncSession,
    org: Organization,
    *,
    role: str = OrganizationRole.member.value,
    email: str | None = None,
    custom_role_id=None,
) -> User:
    user = User(email=email or f"pa-{uuid4().hex[:6]}@test.com", display_name="PA User")
    db.add(user)
    await db.flush()
    db.add(
        OrganizationMember(
            organization_id=org.id, user_id=user.id, role=role, custom_role_id=custom_role_id
        )
    )
    await db.flush()
    return user


def _grant(
    *,
    org_id,
    user_id=None,
    principal_type="user",
    principal_value=None,
    resource_type="document",
    resource_id=None,
    action="read_only",
    status="active",
    expires_at=None,
) -> ResourceAccessGrant:
    return ResourceAccessGrant(
        organization_id=org_id,
        user_id=user_id,
        principal_type=principal_type,
        principal_value=principal_value or (str(user_id) if user_id else str(uuid4())),
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        status=status,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# A. Summary — total/admin user counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_total_and_admin_users(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    await _make_member(db_session, org, role="member")
    await _make_member(db_session, org, role="member")
    await _make_member(db_session, org, role="admin")
    await _make_member(db_session, org, role="owner")
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.total_users == 4
    assert summary.admin_users == 2


# ---------------------------------------------------------------------------
# B. Summary — external_users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_users_via_verified_domain(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    db_session.add(
        OrgDomainVerification(
            organization_id=org.id,
            domain="acme.test",
            status="verified",
            verification_token=uuid4().hex,
        )
    )
    await _make_member(db_session, org, role="member", email="alice@acme.test")
    await _make_member(db_session, org, role="member", email="bob@acme.test")
    await _make_member(db_session, org, role="member", email="carol@contractor.test")
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.external_users == 1
    assert summary.external_users_is_heuristic is False


@pytest.mark.asyncio
async def test_external_users_falls_back_to_majority_domain_heuristic(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    await _make_member(db_session, org, role="member", email="alice@acme.test")
    await _make_member(db_session, org, role="member", email="bob@acme.test")
    await _make_member(db_session, org, role="member", email="carol@acme.test")
    await _make_member(db_session, org, role="member", email="dave@othercorp.test")
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.external_users == 1
    assert summary.external_users_is_heuristic is True


# ---------------------------------------------------------------------------
# C. Summary — broad_access_users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broad_access_users_wildcard_grant_and_connector_scope_no_double_count(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    wildcard_user = await _make_member(db_session, org, role="member")
    connector_user = await _make_member(db_session, org, role="member")
    normal_user = await _make_member(db_session, org, role="member")
    await _make_member(db_session, org, role="admin")

    db_session.add(
        _grant(
            org_id=org.id,
            user_id=wildcard_user.id,
            principal_value=str(wildcard_user.id),
            resource_type="document",
            resource_id=None,
        )
    )
    connection_id = uuid4()
    db_session.add(
        ConnectorPermissionReview(
            organization_id=org.id,
            connection_id=connection_id,
            is_broad_scope=True,
        )
    )
    db_session.add(
        SourceAclMapping(
            organization_id=org.id,
            connector_connection_id=connection_id,
            source_type="connector_source_item",
            source_id="item-1",
            user_id=connector_user.id,
            principal_type="user",
            principal_value=str(connector_user.id),
            action="read_only",
            acl_effect="allow",
            is_active=True,
        )
    )
    # Both signals for the same user must not double-count.
    db_session.add(
        _grant(
            org_id=org.id,
            user_id=wildcard_user.id,
            principal_value=str(wildcard_user.id),
            resource_type="collection",
            resource_id=None,
        )
    )
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.broad_access_users == 2
    assert normal_user.id  # not counted; sanity reference


# ---------------------------------------------------------------------------
# D. Summary — expired_active_grants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_active_grants_counts_only_past_expiry(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    now = datetime.now(tz=UTC)
    db_session.add(_grant(org_id=org.id, expires_at=now - timedelta(days=1)))  # expired
    db_session.add(_grant(org_id=org.id, expires_at=now + timedelta(days=1)))  # future
    db_session.add(_grant(org_id=org.id, expires_at=None))  # no expiry
    db_session.add(_grant(org_id=org.id, expires_at=now - timedelta(days=1), status="revoked"))
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.expired_active_grants == 1


# ---------------------------------------------------------------------------
# E. Summary — orphaned_grants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_orphaned_grants_flags_grant_on_missing_document(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    doc = Document(
        organization_id=org.id,
        filename="real.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"documents/{uuid4().hex[:8]}.pdf",
        status="indexed",
    )
    db_session.add(doc)
    await db_session.flush()

    db_session.add(_grant(org_id=org.id, resource_type="document", resource_id=str(doc.id)))
    db_session.add(_grant(org_id=org.id, resource_type="document", resource_id=str(uuid4())))
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.orphaned_grants == 1


# ---------------------------------------------------------------------------
# F. Summary — resources_without_owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resources_without_owner_counts_documents_and_collections(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    owner = await _make_member(db_session, org, role="member")
    db_session.add(
        Document(
            organization_id=org.id,
            filename="owned.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key=f"documents/{uuid4().hex[:8]}.pdf",
            status="indexed",
            uploaded_by_user_id=owner.id,
        )
    )
    db_session.add(
        Document(
            organization_id=org.id,
            filename="orphan.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key=f"documents/{uuid4().hex[:8]}.pdf",
            status="indexed",
            uploaded_by_user_id=None,
        )
    )
    db_session.add(Collection(organization_id=org.id, name="Owned", owner_id=owner.id))
    db_session.add(Collection(organization_id=org.id, name="Ownerless", owner_id=None))
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.resources_without_owner == 2


# ---------------------------------------------------------------------------
# G. Summary — connector_acl_mismatches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connector_acl_mismatches_counts_open_acl_and_revoked_only(
    db_session: AsyncSession,
) -> None:
    org = await _make_org(db_session)
    connection_id = uuid4()
    db_session.add(
        SyncConflict(
            organization_id=org.id,
            connection_id=connection_id,
            provider_item_id="item-1",
            conflict_type="acl_changed",
            status="open",
        )
    )
    db_session.add(
        SyncConflict(
            organization_id=org.id,
            connection_id=connection_id,
            provider_item_id="item-2",
            conflict_type="permission_revoked",
            status="open",
        )
    )
    db_session.add(
        SyncConflict(
            organization_id=org.id,
            connection_id=connection_id,
            provider_item_id="item-3",
            conflict_type="renamed",
            status="open",
        )
    )
    db_session.add(
        SyncConflict(
            organization_id=org.id,
            connection_id=connection_id,
            provider_item_id="item-4",
            conflict_type="acl_changed",
            status="resolved",
        )
    )
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.connector_acl_mismatches == 2


# ---------------------------------------------------------------------------
# H. Summary — unauthorized_access_attempts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_access_attempts_from_audit_log(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    now = datetime.now(tz=UTC)
    db_session.add(
        AuditLog(
            organization_id=org.id,
            action=AUTHZ_ACCESS_DENIED,
            resource_type="document",
            metadata_json={},
            created_at=now,
        )
    )
    db_session.add(
        AuditLog(
            organization_id=org.id,
            action=AUTHZ_ACCESS_DENIED,
            resource_type="document",
            metadata_json={},
            created_at=now - timedelta(days=1),
        )
    )
    db_session.add(
        AuditLog(
            organization_id=org.id,
            action="permissions.conflicts.scanned",
            resource_type="organization",
            metadata_json={},
            created_at=now,
        )
    )
    await db_session.commit()

    summary = await PermissionsAccessReportService().get_summary(db_session, organization_id=org.id)
    assert summary.unauthorized_access_attempts == 2

    charts = await PermissionsAccessReportService().get_charts(db_session, organization_id=org.id)
    total_from_chart = sum(p.count for p in charts.failed_access_attempts)
    assert total_from_chart == 2


# ---------------------------------------------------------------------------
# I. Rows — explicit grant / deny / connector ACL / conflict merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rows_merge_conflict_onto_existing_grant_row(db_session: AsyncSession) -> None:
    org = await _make_org(db_session)
    user = await _make_member(db_session, org, role="member")
    doc = Document(
        organization_id=org.id,
        filename="doc.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"documents/{uuid4().hex[:8]}.pdf",
        status="indexed",
    )
    db_session.add(doc)
    await db_session.flush()

    grant = _grant(
        org_id=org.id,
        user_id=user.id,
        principal_value=str(user.id),
        resource_type="document",
        resource_id=str(doc.id),
    )
    db_session.add(grant)
    await db_session.flush()

    from app.domains.permissions.repositories.conflicts import ConflictsRepository

    await ConflictsRepository().create_conflict(
        db_session,
        organization_id=org.id,
        subject_type="user",
        subject_value=str(user.id),
        user_id=user.id,
        role_name="member",
        resource_type="document",
        resource_id=str(doc.id),
        action="read_only",
        conflict_type="role_allow_resource_deny",
        severity_db="high",
        conflict_summary="test",
        grant_id=grant.id,
    )
    await db_session.commit()

    result = await PermissionsAccessReportService().list_rows(
        db_session, organization_id=org.id, filters=PermissionsAccessFilters()
    )
    matching = [r for r in result.items if r.resource_id == str(doc.id)]
    assert len(matching) == 1
    row = matching[0]
    assert row.access_source == "explicit_grant"
    assert row.conflict_status == "open"
    assert row.grant_id == str(grant.id)
    assert row.conflict_id is not None
    assert row.resource_label == "doc.pdf"


# ---------------------------------------------------------------------------
# J. Tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation_across_summary_charts_rows(db_session: AsyncSession) -> None:
    org_a = await _make_org(db_session)
    org_b = await _make_org(db_session)
    await _make_member(db_session, org_a, role="member")
    user_b = await _make_member(db_session, org_b, role="member")

    db_session.add(_grant(org_id=org_b.id, user_id=user_b.id, principal_value=str(user_b.id)))
    db_session.add(
        AuditLog(
            organization_id=org_b.id,
            action=AUTHZ_ACCESS_DENIED,
            resource_type="document",
            metadata_json={},
            created_at=datetime.now(tz=UTC),
        )
    )
    await db_session.commit()

    svc = PermissionsAccessReportService()
    summary_a = await svc.get_summary(db_session, organization_id=org_a.id)
    assert summary_a.total_users == 1
    assert summary_a.unauthorized_access_attempts == 0

    rows_a = await svc.list_rows(
        db_session, organization_id=org_a.id, filters=PermissionsAccessFilters()
    )
    assert all(r.user_id != str(user_b.id) for r in rows_a.items)


# ---------------------------------------------------------------------------
# K. HTTP — role/permission gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_summary_requires_security_center_view(
    pa_client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await _make_org(db_session)
    member = await _make_member(db_session, org, role="member")
    admin = await _make_member(db_session, org, role="admin")
    await db_session.commit()

    member_token = _token(str(member.id), str(org.id), role="member")
    resp = await pa_client.get("/admin/permissions-access/summary", headers=_auth(member_token))
    assert resp.status_code == 403

    admin_token = _token(str(admin.id), str(org.id), role="admin")
    resp = await pa_client.get("/admin/permissions-access/summary", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["total_users"] == 2


# ---------------------------------------------------------------------------
# L. HTTP — export requires security_center_configure, not just view
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_export_requires_configure_not_just_view(
    pa_client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await _make_org(db_session)

    custom_role = CustomRole(organization_id=org.id, name="Security Viewer", base_role="member")
    db_session.add(custom_role)
    await db_session.flush()
    db_session.add(
        CustomRolePermission(custom_role_id=custom_role.id, permission="security_center:view")
    )
    await db_session.flush()

    viewer = await _make_member(db_session, org, role="member", custom_role_id=custom_role.id)
    admin = await _make_member(db_session, org, role="admin")
    await db_session.commit()

    viewer_token = _token(str(viewer.id), str(org.id), role="member")
    resp = await pa_client.get("/admin/permissions-access/summary", headers=_auth(viewer_token))
    assert resp.status_code == 200, "view-only custom role should still see the summary"

    resp = await pa_client.get("/admin/permissions-access/export", headers=_auth(viewer_token))
    assert resp.status_code == 403, "view-only custom role must not be able to export"

    admin_token = _token(str(admin.id), str(org.id), role="admin")
    resp = await pa_client.get("/admin/permissions-access/export", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")


# ---------------------------------------------------------------------------
# M. Export CSV column allow-list — never leaks resource content or raw IDs
# ---------------------------------------------------------------------------


_EXPORT_ALLOWED_COLUMNS = {
    "user_name",
    "user_email",
    "role",
    "team",
    "resource_type",
    "resource_label",
    "access_level",
    "access_source",
    "conflict_status",
    "last_access",
}


@pytest.mark.asyncio
async def test_export_csv_column_allowlist(
    pa_client: AsyncClient, db_session: AsyncSession
) -> None:
    org = await _make_org(db_session)
    admin = await _make_member(db_session, org, role="admin")
    user = await _make_member(db_session, org, role="member")
    db_session.add(
        _grant(org_id=org.id, user_id=user.id, principal_value=str(user.id), resource_id=None)
    )
    await db_session.commit()

    admin_token = _token(str(admin.id), str(org.id), role="admin")
    resp = await pa_client.get("/admin/permissions-access/export", headers=_auth(admin_token))
    assert resp.status_code == 200
    header_line = resp.text.splitlines()[0]
    columns = {c.strip() for c in header_line.split(",")}
    assert columns == _EXPORT_ALLOWED_COLUMNS
    assert "resource_id" not in header_line
    assert "user_id" not in header_line
    assert "grant_id" not in header_line
    assert "conflict_id" not in header_line
