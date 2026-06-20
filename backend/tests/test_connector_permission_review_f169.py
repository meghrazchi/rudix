"""Tests for F169: Connector permission review — scope analysis, review CRUD, sync gate."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
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

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.domains.connectors.services.permission_review_service import (
    PermissionReviewNotFoundError,
    PermissionReviewService,
    ScopeWarning,
    analyze_scopes,
)
from app.main import app
from app.models.connector import (
    ConnectorConnection,
    ConnectorProvider,
)
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class ReviewContext:
    org_id: UUID
    user_id: UUID
    connection: ConnectorConnection


async def _create_context(
    db_session: AsyncSession,
    provider_key: str = "google_drive",
    scopes: list[str] | None = None,
) -> ReviewContext:
    org = Organization(name=f"ReviewOrg {uuid4()}", slug=f"review-{uuid4().hex[:8]}")
    db_session.add(org)
    await db_session.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"review-user-{uuid4()}",
        email=f"review-{uuid4().hex[:8]}@example.test",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="admin"))
    await db_session.flush()

    provider = ConnectorProvider(
        key=provider_key,
        display_name=f"Test {provider_key}",
        auth_type="oauth2",
        capabilities_json=[],
        config_schema_json={},
        rate_limits_json=[],
        export_formats_json=[],
    )
    db_session.add(provider)
    await db_session.flush()

    connection = ConnectorConnection(
        organization_id=org.id,
        provider_id=provider.id,
        created_by_user_id=user.id,
        display_name="Test connection",
        status="active",
        auth_config_json={"provider_key": provider_key},
    )
    db_session.add(connection)
    await db_session.flush()

    return ReviewContext(org_id=org.id, user_id=user.id, connection=connection)


# ---------------------------------------------------------------------------
# Scope analysis unit tests
# ---------------------------------------------------------------------------


class TestAnalyzeScopes:
    def test_no_scopes_returns_empty(self) -> None:
        warnings, is_broad = analyze_scopes([], provider_key="google_drive")
        assert warnings == []
        assert is_broad is False

    def test_readonly_scope_no_filter_org_wide(self) -> None:
        warnings, is_broad = analyze_scopes(
            ["https://www.googleapis.com/auth/drive.readonly"],
            provider_key="google_drive",
        )
        assert is_broad is True
        assert any(w.code == "org_wide_access" for w in warnings)

    def test_readonly_scope_with_filter_no_warning(self) -> None:
        warnings, is_broad = analyze_scopes(
            ["https://www.googleapis.com/auth/drive.readonly"],
            provider_key="google_drive",
            source_config={"folder_ids": ["abc123"]},
        )
        assert is_broad is False
        assert warnings == []

    def test_write_scope_flagged(self) -> None:
        warnings, is_broad = analyze_scopes(
            ["write:confluence-content"],
            provider_key="confluence",
        )
        assert is_broad is True
        assert any(w.code == "write_permission" for w in warnings)

    def test_admin_scope_flagged(self) -> None:
        warnings, is_broad = analyze_scopes(
            ["admin:org:all"],
            provider_key="jira",
        )
        assert is_broad is True
        assert any(w.code == "admin_scope" for w in warnings)

    def test_generic_dot_all_scope_flagged(self) -> None:
        warnings, is_broad = analyze_scopes(
            ["read:users.all"],
            provider_key="github",
        )
        assert is_broad is True
        assert any(w.code == "broad_read" for w in warnings)

    def test_microsoft_sites_read_all_no_filter_org_wide(self) -> None:
        warnings, is_broad = analyze_scopes(
            ["Sites.Read.All", "Files.Read.All"],
            provider_key="microsoft-sharepoint-onedrive",
        )
        assert is_broad is True
        assert any(w.code == "org_wide_access" for w in warnings)

    def test_microsoft_sites_read_all_with_site_filter(self) -> None:
        _warnings, is_broad = analyze_scopes(
            ["Sites.Read.All"],
            provider_key="microsoft-sharepoint-onedrive",
            source_config={"site_ids": ["site-abc"]},
        )
        assert is_broad is False

    def test_scope_warning_to_dict(self) -> None:
        w = ScopeWarning(code="broad_read", message="msg", scope="read:x.all")
        d = w.to_dict()
        assert d == {"code": "broad_read", "message": "msg", "scope": "read:x.all"}

    def test_multiple_warnings_collected(self) -> None:
        warnings, is_broad = analyze_scopes(
            [
                "https://www.googleapis.com/auth/drive.readonly",
                "write:drive.files",
            ],
            provider_key="google_drive",
        )
        assert is_broad is True
        codes = {w.code for w in warnings}
        assert "write_permission" in codes


# ---------------------------------------------------------------------------
# PermissionReviewService integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPermissionReviewService:
    async def test_get_or_create_generates_for_new_connection(
        self, db_session: AsyncSession
    ) -> None:
        ctx = await _create_context(db_session)
        service = PermissionReviewService()

        review = await service.get_or_create(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        await db_session.commit()

        assert review.connection_id == ctx.connection.id
        assert review.is_confirmed is False
        assert isinstance(review.permission_snapshot_json, dict)
        assert isinstance(review.scope_warnings_json, list)

    async def test_get_or_create_returns_existing(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session)
        service = PermissionReviewService()

        first = await service.get_or_create(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        await db_session.flush()
        first_id = first.id

        second = await service.get_or_create(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        assert second.id == first_id

    async def test_confirm_sets_confirmed_and_reviewer(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session)
        service = PermissionReviewService()

        review = await service.confirm(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
            user_id=ctx.user_id,
        )
        await db_session.commit()

        assert review.is_confirmed is True
        assert review.reviewed_by_user_id == ctx.user_id
        assert review.reviewed_at is not None

    async def test_is_confirmed_false_before_confirmation(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session)
        service = PermissionReviewService()

        confirmed = await service.is_confirmed(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        assert confirmed is False

    async def test_is_confirmed_true_after_confirmation(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session)
        service = PermissionReviewService()

        await service.confirm(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
            user_id=ctx.user_id,
        )
        await db_session.flush()

        confirmed = await service.is_confirmed(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        assert confirmed is True

    async def test_get_or_create_missing_connection_raises(self, db_session: AsyncSession) -> None:
        org = Organization(name="Missing org", slug=f"missing-{uuid4().hex[:8]}")
        db_session.add(org)
        await db_session.flush()

        service = PermissionReviewService()
        with pytest.raises(PermissionReviewNotFoundError):
            await service.get_or_create(
                db_session,
                organization_id=org.id,
                connection_id=uuid4(),
            )

    async def test_snapshot_captures_provider_key(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session, provider_key="confluence")
        service = PermissionReviewService()

        review = await service.get_or_create(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        await db_session.flush()

        assert review.permission_snapshot_json.get("provider_key") == "confluence"
        assert review.permission_snapshot_json.get("sync_direction") == "read_only"

    async def test_broad_scope_detected_from_credential_scopes(
        self, db_session: AsyncSession
    ) -> None:
        from app.models.connector_credential import ConnectorCredential

        ctx = await _create_context(db_session, provider_key="google_drive")
        cred = ConnectorCredential(
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
            auth_type="oauth2",
            status="active",
            encrypted_payload="dummy",
            encryption_key_id="key1",
            encryption_algorithm="AES-256-GCM",
            secret_fingerprint="f" * 64,
            scopes_json=["https://www.googleapis.com/auth/drive.readonly"],
            is_current=True,
        )
        db_session.add(cred)
        await db_session.flush()

        service = PermissionReviewService()
        review = await service.get_or_create(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        await db_session.flush()

        assert review.is_broad_scope is True
        assert len(review.scope_warnings_json) > 0


# ---------------------------------------------------------------------------
# HTTP endpoint tests (minimal — service logic tested above)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPermissionReviewEndpoints:
    async def test_get_review_creates_and_returns(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session)
        await db_session.commit()

        # Simulate the GET endpoint by calling the service directly and checking response shape
        service = PermissionReviewService()
        review = await service.get_or_create(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        await db_session.commit()

        assert review.id is not None
        assert review.is_confirmed is False
        assert "provider_key" in review.permission_snapshot_json

    async def test_confirm_review_via_service(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session)
        service = PermissionReviewService()

        review = await service.confirm(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
            user_id=ctx.user_id,
        )
        await db_session.commit()

        assert review.is_confirmed is True
        assert review.reviewed_at is not None

    async def test_sync_blocked_when_review_not_confirmed(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session)
        service = PermissionReviewService()

        is_ok = await service.is_confirmed(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        assert is_ok is False

    async def test_sync_allowed_after_confirmation(self, db_session: AsyncSession) -> None:
        ctx = await _create_context(db_session)
        service = PermissionReviewService()

        await service.confirm(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
            user_id=ctx.user_id,
        )
        await db_session.flush()

        is_ok = await service.is_confirmed(
            db_session,
            organization_id=ctx.org_id,
            connection_id=ctx.connection.id,
        )
        assert is_ok is True


@pytest.mark.asyncio
async def test_confirm_permission_review_endpoint_returns_serializable_review(
    db_session: AsyncSession,
) -> None:
    ctx = await _create_context(db_session, provider_key="confluence")

    principal = AuthenticatedPrincipal(
        user_id=str(ctx.user_id),
        organization_id=str(ctx.org_id),
        roles=[OrganizationRole.admin.value],
        auth_provider="test",
    )

    async def _override_db() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[get_db_session] = _override_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/api/v1/connectors/{ctx.connection.id}/permission-review/confirm",
            )
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
        app.dependency_overrides.pop(get_db_session, None)

    assert response.status_code == 200
    data = response.json()
    assert data["connection_id"] == str(ctx.connection.id)
    assert data["is_confirmed"] is True
    assert data["updated_at"]
