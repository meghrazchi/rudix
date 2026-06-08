"""Connector platform observability and rollout smoke tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, ConnectorRolloutStage, settings
from app.db.session import get_db_session
from app.domains.connectors.services.connector_service import ConnectorPlatformService
from app.main import app
from app.models.connector import ExternalItem
from app.models.connector_source import SourceDocument, SourceReference
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.document import Document
from app.models.enums import (
    ConnectorSyncRunStatus,
    DocumentStatus,
    ExternalItemType,
    ExternalItemVisibility,
    OrganizationRole,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


@pytest_asyncio.fixture
async def connector_client(
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


def _make_token(user_id: str, org_id: str, role: str = OrganizationRole.admin.value) -> str:
    del role
    return create_app_access_token(subject=user_id, organization_id=org_id)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _make_org_user(db: AsyncSession) -> dict[str, str]:
    slug = f"connector-org-{uuid4().hex[:8]}"
    org = Organization(name=f"Connector Org {slug}", slug=slug)
    db.add(org)
    await db.flush()

    user = User(
        organization_id=org.id,
        external_auth_id=f"connector-user-{uuid4().hex[:8]}",
        email=f"connector-{uuid4().hex[:6]}@test.com",
        display_name="Connector User",
    )
    db.add(user)
    await db.flush()

    member = OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.admin.value,
    )
    db.add(member)
    await db.flush()

    return {
        "org_id": str(org.id),
        "user_id": str(user.id),
        "token": _make_token(str(user.id), str(org.id)),
    }


async def _seed_connector_health_data(db_session: AsyncSession) -> dict[str, str]:
    ctx = await _make_org_user(db_session)
    org_id = UUID(ctx["org_id"])
    user_id = UUID(ctx["user_id"])
    service = ConnectorPlatformService()

    connection = await service.create_connection(
        db_session,
        organization_id=org_id,
        provider_key="confluence",
        display_name="Confluence Production",
        created_by_user_id=user_id,
        external_account_id="confluence-site-1",
    )
    source = await service.create_external_source(
        db_session,
        organization_id=org_id,
        connection_id=connection.id,
        provider_source_id="ENG",
        source_type="confluence_space",
        name="Engineering",
        source_url="https://confluence.example.test/spaces/ENG",
    )

    job = ConnectorSyncJob(
        organization_id=org_id,
        connection_id=connection.id,
        external_source_id=source.id,
        name="Confluence Sync",
        status="active",
        schedule_json={"type": "interval", "interval_minutes": 60},
        cursor_json={},
    )
    db_session.add(job)
    await db_session.flush()

    ext_item = ExternalItem(
        organization_id=org_id,
        connection_id=connection.id,
        external_source_id=source.id,
        collection_id=None,
        provider_item_id="ENG-1",
        provider_parent_id=None,
        root_provider_item_id=None,
        item_type=ExternalItemType.cloud_file.value,
        title="Specs",
        source_url="https://confluence.example.test/pages/ENG-1",
        content_hash="a" * 64,
        source_updated_at=datetime.now(tz=UTC) - timedelta(hours=1),
        sync_version=1,
        mime_type="application/pdf",
        visibility=ExternalItemVisibility.org_wide.value,
        acl_hash=None,
        metadata_json={},
        permissions_json={},
    )
    db_session.add(ext_item)
    await db_session.flush()

    document = Document(
        organization_id=org_id,
        uploaded_by_user_id=user_id,
        filename="specs.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"connectors/{org_id}/specs.pdf",
        status=DocumentStatus.indexed.value,
        page_count=3,
        chunk_count=2,
        ingestion_source="connector",
        connector_external_item_id=ext_item.id,
    )
    db_session.add(document)
    await db_session.flush()

    source_document = SourceDocument(
        organization_id=org_id,
        external_item_id=ext_item.id,
        document_id=document.id,
        collection_id=None,
        sync_run_id=None,
        content_hash="b" * 64,
        sync_version=1,
        status="active",
    )
    db_session.add(source_document)
    await db_session.flush()

    db_session.add(
        SourceReference(
            organization_id=org_id,
            source_document_id=source_document.id,
            external_item_id=ext_item.id,
            document_id=document.id,
            chunk_id=None,
            reference_type="document",
            source_url="https://confluence.example.test/pages/ENG-1",
            title="Specs",
            locator_json={},
            metadata_json={"provider_key": "confluence"},
        )
    )

    now = datetime.now(tz=UTC)
    db_session.add_all(
        [
            ConnectorSyncRun(
                organization_id=org_id,
                sync_job_id=job.id,
                connection_id=connection.id,
                external_source_id=source.id,
                status=ConnectorSyncRunStatus.completed.value,
                sync_version=101,
                started_at=now - timedelta(minutes=4),
                completed_at=now - timedelta(minutes=3),
                items_seen=5,
                items_upserted=2,
                items_deleted=1,
                cursor_before_json={},
                cursor_after_json={"cursor": "next"},
                trigger_type="scheduled",
                error_message=None,
                error_details_json={},
            ),
            ConnectorSyncRun(
                organization_id=org_id,
                sync_job_id=job.id,
                connection_id=connection.id,
                external_source_id=source.id,
                status=ConnectorSyncRunStatus.failed.value,
                sync_version=102,
                started_at=now - timedelta(minutes=2),
                completed_at=now - timedelta(minutes=1),
                items_seen=3,
                items_upserted=1,
                items_deleted=0,
                cursor_before_json={},
                cursor_after_json={},
                trigger_type="manual",
                error_message="rate limit",
                error_details_json={"code": "rate_limit", "retry_after_seconds": 45},
            ),
            AuditLog(
                organization_id=org_id,
                user_id=None,
                action="connector.oauth.refresh_failed",
                resource_type="connector_connection",
                resource_id=connection.id,
                metadata_json={"provider_key": "confluence"},
            ),
            AuditLog(
                organization_id=org_id,
                user_id=None,
                action="connector.sync.retry_scheduled",
                resource_type="connector_sync_run",
                resource_id=None,
                metadata_json={"provider_key": "confluence"},
            ),
            AuditLog(
                organization_id=org_id,
                user_id=None,
                action="connector.sync.item.skipped",
                resource_type="external_item",
                resource_id=ext_item.id,
                metadata_json={"provider_key": "confluence"},
            ),
            AuditLog(
                organization_id=org_id,
                user_id=None,
                action="connector.ingestion.failed",
                resource_type="external_item",
                resource_id=ext_item.id,
                metadata_json={"provider_key": "confluence"},
            ),
        ]
    )
    await db_session.flush()
    return ctx


@pytest.mark.asyncio
async def test_connector_platform_health_reports_provider_metrics(
    connector_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    ctx = await _seed_connector_health_data(db_session)

    response = await connector_client.get(
        "/api/v1/admin/connectors/health",
        headers=_auth(ctx["token"]),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["feature_enabled"] is True
    assert data["overall_status"] == "degraded"
    assert data["totals"]["connection_count"] == 1
    assert data["totals"]["total_runs"] == 2
    assert data["totals"]["failed_runs"] == 1
    assert data["totals"]["rate_limited_runs"] == 1
    assert data["totals"]["retry_events"] == 1
    assert data["totals"]["skipped_items"] == 1
    assert data["totals"]["ingestion_failures"] == 1
    assert data["totals"]["token_refresh_failures"] == 1
    assert data["totals"]["citation_usage"] == 1
    assert data["totals"]["connector_documents"] == 1
    assert data["providers"][0]["provider_key"] == "confluence"
    assert data["providers"][0]["top_error_codes"][0]["code"] == "rate_limit"


@pytest.mark.asyncio
async def test_connector_platform_health_marks_disabled_rollout(
    connector_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = await _seed_connector_health_data(db_session)
    monkeypatch.setattr(settings, "connector_rollout_stage", ConnectorRolloutStage.off)
    monkeypatch.setattr(settings, "feature_enable_connectors", True)

    response = await connector_client.get(
        "/api/v1/admin/connectors/health",
        headers=_auth(ctx["token"]),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["feature_enabled"] is False
    assert data["overall_status"] == "disabled"


@pytest.mark.asyncio
async def test_connector_routes_reject_when_rollout_disabled(
    connector_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = await _make_org_user(db_session)
    monkeypatch.setattr(settings, "connector_rollout_stage", ConnectorRolloutStage.off)
    monkeypatch.setattr(settings, "feature_enable_connectors", True)

    response = await connector_client.post(
        "/api/v1/connectors/connections",
        headers=_auth(ctx["token"]),
        json={
            "provider_key": "confluence",
            "display_name": "Confluence Production",
            "external_account_id": "confluence-site-1",
            "config": {},
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "connector platform is disabled for this deployment"
