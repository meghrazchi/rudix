"""Tests for F335: Authorization conflict detection service.

Covers:
- role_allow_resource_deny: grant + deny on same principal/resource/action
- No duplicate conflict creation (idempotency)
- Conflict upsert skips existing open conflicts
- ConflictsRepository CRUD: create, list, get, update status
- Remediation catalog returns non-empty lists for known types
- ScanResult shape is correct
"""

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
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

from datetime import UTC, datetime

from app.domains.permissions.repositories.conflicts import ConflictsRepository
from app.domains.permissions.schemas.conflicts import (
    CONFLICT_TYPES,
    DB_TO_SEVERITY,
    SEVERITY_TO_DB,
    remediation_for,
)
from app.domains.permissions.services.conflict_detection_service import ConflictDetectionService
from app.models.authorization import ResourceAccessDeny, ResourceAccessGrant, SourceAclMapping
from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.collection import Collection, CollectionDocument
from app.models.connector import ConnectorConnection, ConnectorProvider, ExternalItem
from app.models.document import Document, DocumentChunk
from app.models.enums import ConnectorAuthType, ExternalItemType
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ─── shared connector/collection seeding helpers (F354) ────────────────────────


async def _seed_org(db: AsyncSession) -> Organization:
    org = Organization(name=f"Org {uuid4()}", slug=f"org-{uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    return org


async def _seed_member(db: AsyncSession, *, org_id, role: str = "member") -> User:
    user = User(
        organization_id=org_id,
        external_auth_id=f"user-{uuid4()}",
        email=f"{uuid4().hex[:8]}@example.test",
    )
    db.add(user)
    await db.flush()
    db.add(OrganizationMember(organization_id=org_id, user_id=user.id, role=role))
    await db.flush()
    return user


async def _seed_connector_document(
    db: AsyncSession,
    *,
    org_id,
    connection_status: str = "active",
) -> tuple[ConnectorConnection, ExternalItem, Document]:
    provider = ConnectorProvider(
        key=f"provider-{uuid4().hex[:8]}",
        display_name="Test Provider",
        auth_type=ConnectorAuthType.oauth2.value,
        capabilities_json=[],
        config_schema_json={},
        rate_limits_json=[],
        export_formats_json=[],
        is_enabled=True,
    )
    db.add(provider)
    await db.flush()

    connection = ConnectorConnection(
        organization_id=org_id,
        provider_id=provider.id,
        display_name="Test Connection",
        status=connection_status,
        auth_config_json={},
    )
    db.add(connection)
    await db.flush()

    external_item = ExternalItem(
        organization_id=org_id,
        connection_id=connection.id,
        provider_item_id=f"item-{uuid4().hex[:8]}",
        item_type=ExternalItemType.cloud_file.value,
        title="Source Title",
        source_url=f"https://example.test/items/{uuid4().hex[:8]}",
        content_hash="a" * 64,
        source_updated_at=datetime.now(UTC),
        sync_version=1,
        visibility="restricted",
        metadata_json={},
        permissions_json={},
    )
    db.add(external_item)
    await db.flush()

    document = Document(
        organization_id=org_id,
        filename="source.pdf",
        file_type="pdf",
        storage_bucket="documents",
        storage_object_key=f"documents/{uuid4().hex[:8]}.pdf",
        status="indexed",
        connector_external_item_id=external_item.id,
        ingestion_source="connector",
    )
    db.add(document)
    await db.flush()

    return connection, external_item, document


async def _seed_document_chunk(db: AsyncSession, *, document_id) -> DocumentChunk:
    chunk = DocumentChunk(
        document_id=document_id,
        page_number=1,
        chunk_index=0,
        text="Chunk text.",
        token_count=10,
        embedding_model="test-embedding",
        index_version="v1",
        qdrant_point_id=str(uuid4()),
    )
    db.add(chunk)
    await db.flush()
    return chunk


# ─── helpers ──────────────────────────────────────────────────────────────────


async def _seed_grant(
    db: AsyncSession,
    *,
    org_id,
    principal_type: str = "user",
    principal_value: str | None = None,
    resource_type: str = "document",
    resource_id: str | None = None,
    action: str = "read_only",
) -> ResourceAccessGrant:
    g = ResourceAccessGrant(
        organization_id=org_id,
        principal_type=principal_type,
        principal_value=principal_value or str(uuid4()),
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        status="active",
    )
    db.add(g)
    await db.flush()
    return g


async def _seed_deny(
    db: AsyncSession,
    *,
    org_id,
    principal_type: str = "user",
    principal_value: str,
    resource_type: str = "document",
    resource_id: str | None = None,
    action: str = "read_only",
) -> ResourceAccessDeny:
    d = ResourceAccessDeny(
        organization_id=org_id,
        principal_type=principal_type,
        principal_value=principal_value,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        status="active",
    )
    db.add(d)
    await db.flush()
    return d


# ─── severity mapping ──────────────────────────────────────────────────────────


class TestSeverityMapping:
    def test_all_api_severities_map_to_db(self) -> None:
        for api_sev in ("info", "warning", "blocking", "security_risk"):
            assert api_sev in SEVERITY_TO_DB

    def test_all_db_severities_map_back(self) -> None:
        for db_sev in ("low", "medium", "high", "critical"):
            assert db_sev in DB_TO_SEVERITY

    def test_round_trip(self) -> None:
        for api_sev, db_sev in SEVERITY_TO_DB.items():
            assert DB_TO_SEVERITY[db_sev] == api_sev


# ─── remediation catalog ───────────────────────────────────────────────────────


class TestRemediationCatalog:
    def test_all_conflict_types_have_remediation(self) -> None:
        for ct in CONFLICT_TYPES:
            result = remediation_for(ct)
            assert isinstance(result, list)
            assert len(result) >= 1

    def test_unknown_type_returns_fallback(self) -> None:
        result = remediation_for("totally_unknown_conflict_type")
        assert len(result) >= 1
        assert "manually" in result[0].lower()


# ─── repository CRUD ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestConflictsRepository:
    async def test_create_and_get_conflict(self, db_session: AsyncSession) -> None:
        repo = ConflictsRepository()
        org_id = uuid4()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org_id,
            subject_type="user",
            subject_value="user-abc",
            user_id=None,
            role_name="member",
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="high",
            conflict_summary="Test conflict",
            context={"test": True},
        )
        await db_session.flush()

        fetched = await repo.get_conflict(
            db_session, conflict_id=conflict.id, organization_id=org_id
        )
        assert fetched is not None
        assert fetched.conflict_type == "role_allow_resource_deny"
        assert fetched.severity == "high"
        assert fetched.status == "open"

    async def test_list_conflicts_filtered_by_status(self, db_session: AsyncSession) -> None:
        repo = ConflictsRepository()
        org_id = uuid4()
        for sev in ("high", "low"):
            await repo.create_conflict(
                db_session,
                organization_id=org_id,
                subject_type="user",
                subject_value=f"user-{sev}",
                user_id=None,
                role_name=None,
                resource_type="document",
                resource_id=None,
                action="read_only",
                conflict_type="stale_grant_deleted_resource",
                severity_db=sev,
                conflict_summary="test",
            )
        await db_session.flush()

        items, total = await repo.list_conflicts(db_session, organization_id=org_id, status="open")
        assert total == 2
        assert all(c.status == "open" for c in items)

    async def test_list_conflicts_filtered_by_severity(self, db_session: AsyncSession) -> None:
        repo = ConflictsRepository()
        org_id = uuid4()
        await repo.create_conflict(
            db_session,
            organization_id=org_id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="critical",
            conflict_summary="critical",
        )
        await repo.create_conflict(
            db_session,
            organization_id=org_id,
            subject_type="user",
            subject_value="u2",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id=None,
            action="read_only",
            conflict_type="orphaned_acl_mapping",
            severity_db="low",
            conflict_summary="low",
        )
        await db_session.flush()

        items, total = await repo.list_conflicts(
            db_session, organization_id=org_id, severity_db="critical"
        )
        assert total == 1
        assert items[0].severity == "critical"

    async def test_update_conflict_status_to_resolved(self, db_session: AsyncSession) -> None:
        repo = ConflictsRepository()
        org_id = uuid4()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org_id,
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
        await db_session.flush()
        updated = await repo.update_conflict_status(
            db_session,
            conflict=conflict,
            new_status="resolved",
            resolution_note="Fixed manually",
        )
        assert updated.status == "resolved"
        assert updated.resolved_at is not None

    async def test_get_returns_none_for_wrong_org(self, db_session: AsyncSession) -> None:
        repo = ConflictsRepository()
        org_id = uuid4()
        conflict = await repo.create_conflict(
            db_session,
            organization_id=org_id,
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
        await db_session.flush()
        other_org = uuid4()
        fetched = await repo.get_conflict(
            db_session, conflict_id=conflict.id, organization_id=other_org
        )
        assert fetched is None

    async def test_find_existing_open_conflict(self, db_session: AsyncSession) -> None:
        repo = ConflictsRepository()
        org_id = uuid4()
        await repo.create_conflict(
            db_session,
            organization_id=org_id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="high",
            conflict_summary="existing",
        )
        await db_session.flush()

        found = await repo.find_existing_open_conflict(
            db_session,
            organization_id=org_id,
            subject_value="u1",
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
            conflict_type="role_allow_resource_deny",
        )
        assert found is not None
        assert found.conflict_summary == "existing"

    async def test_find_existing_returns_none_for_different_action(
        self, db_session: AsyncSession
    ) -> None:
        repo = ConflictsRepository()
        org_id = uuid4()
        await repo.create_conflict(
            db_session,
            organization_id=org_id,
            subject_type="user",
            subject_value="u1",
            user_id=None,
            role_name=None,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
            conflict_type="role_allow_resource_deny",
            severity_db="high",
            conflict_summary="existing",
        )
        await db_session.flush()

        found = await repo.find_existing_open_conflict(
            db_session,
            organization_id=org_id,
            subject_value="u1",
            resource_type="document",
            resource_id="doc-1",
            action="manage",  # different action
            conflict_type="role_allow_resource_deny",
        )
        assert found is None


# ─── conflict detection service ────────────────────────────────────────────────


@pytest.mark.asyncio
class TestConflictDetectionService:
    async def test_detects_grant_plus_deny_conflict(self, db_session: AsyncSession) -> None:
        org_id = uuid4()
        principal = "user-" + uuid4().hex[:8]
        await _seed_grant(
            db_session,
            org_id=org_id,
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
        )
        await _seed_deny(
            db_session,
            org_id=org_id,
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
        )
        await db_session.flush()

        svc = ConflictDetectionService()
        # Patch out the raw SQL table lookups (connector_connections, documents)
        with patch.object(svc, "_upsert_conflict", wraps=svc._upsert_conflict):
            result = await svc.scan(db_session, organization_id=org_id)

        assert result.conflicts_detected >= 1
        assert result.scanned_grants >= 1
        assert result.scanned_denies >= 1

    async def test_no_conflict_without_matching_deny(self, db_session: AsyncSession) -> None:
        org_id = uuid4()
        principal = "user-" + uuid4().hex[:8]
        await _seed_grant(
            db_session,
            org_id=org_id,
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
        )
        # deny on different resource_id
        await _seed_deny(
            db_session,
            org_id=org_id,
            principal_value=principal,
            resource_type="document",
            resource_id="doc-2",
            action="read_only",
        )
        await db_session.flush()

        svc = ConflictDetectionService()
        result = await svc.scan(db_session, organization_id=org_id)
        assert result.conflicts_detected == 0

    async def test_scan_is_idempotent(self, db_session: AsyncSession) -> None:
        org_id = uuid4()
        principal = "user-" + uuid4().hex[:8]
        await _seed_grant(
            db_session,
            org_id=org_id,
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
        )
        await _seed_deny(
            db_session,
            org_id=org_id,
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
        )
        await db_session.flush()

        svc = ConflictDetectionService()
        result1 = await svc.scan(db_session, organization_id=org_id)
        result2 = await svc.scan(db_session, organization_id=org_id)

        assert result1.conflicts_created == 1
        assert result2.conflicts_created == 0  # idempotent — no duplicate

    async def test_scan_stats_shape(self, db_session: AsyncSession) -> None:
        org_id = uuid4()
        svc = ConflictDetectionService()
        result = await svc.scan(db_session, organization_id=org_id)
        assert result.scan_duration_ms >= 0
        assert result.scanned_grants == 0
        assert result.scanned_denies == 0
        assert result.conflicts_detected == 0
        assert result.conflicts_created == 0

    async def test_no_cross_org_conflict_detection(self, db_session: AsyncSession) -> None:
        org_a = uuid4()
        org_b = uuid4()
        principal = "user-" + uuid4().hex[:8]
        await _seed_grant(
            db_session,
            org_id=org_a,
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
        )
        await _seed_deny(
            db_session,
            org_id=org_b,  # different org
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
        )
        await db_session.flush()

        svc = ConflictDetectionService()
        result = await svc.scan(db_session, organization_id=org_a)
        assert result.conflicts_detected == 0

    async def test_revoked_grant_not_flagged(self, db_session: AsyncSession) -> None:
        org_id = uuid4()
        principal = "user-" + uuid4().hex[:8]
        revoked = ResourceAccessGrant(
            organization_id=org_id,
            principal_type="user",
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
            status="revoked",
        )
        db_session.add(revoked)
        await _seed_deny(
            db_session,
            org_id=org_id,
            principal_value=principal,
            resource_type="document",
            resource_id="doc-1",
            action="read_only",
        )
        await db_session.flush()

        svc = ConflictDetectionService()
        result = await svc.scan(db_session, organization_id=org_id)
        assert result.conflicts_detected == 0


# ─── F354: collection_allow_connector_acl_deny ─────────────────────────────────


@pytest.mark.asyncio
class TestCollectionAllowConnectorAclDeny:
    async def test_member_bypassing_connector_acl_via_org_wide_collection_is_flagged(
        self, db_session: AsyncSession
    ) -> None:
        org = await _seed_org(db_session)
        allowed_user = await _seed_member(db_session, org_id=org.id, role="member")
        bypassing_user = await _seed_member(db_session, org_id=org.id, role="member")
        await _seed_member(db_session, org_id=org.id, role="admin")

        connection, external_item, document = await _seed_connector_document(
            db_session, org_id=org.id
        )
        db_session.add(
            SourceAclMapping(
                organization_id=org.id,
                connector_connection_id=connection.id,
                source_type="connector_source_item",
                source_id=str(external_item.id),
                user_id=allowed_user.id,
                principal_type="user",
                principal_value=str(allowed_user.id),
                action="read_only",
                acl_effect="allow",
                is_active=True,
            )
        )
        await db_session.flush()

        collection = Collection(organization_id=org.id, name="Org Wide", access_policy="org_wide")
        db_session.add(collection)
        await db_session.flush()
        db_session.add(CollectionDocument(collection_id=collection.id, document_id=document.id))
        await db_session.flush()

        svc = ConflictDetectionService()
        result = await svc.scan(db_session, organization_id=org.id)

        items, _ = await ConflictsRepository().list_conflicts(
            db_session, organization_id=org.id, resource_type="document"
        )
        conflicts = [c for c in items if c.conflict_type == "collection_allow_connector_acl_deny"]
        assert len(conflicts) == 1
        assert conflicts[0].subject_value == str(bypassing_user.id)
        assert conflicts[0].resource_id == str(document.id)
        assert result.conflicts_detected >= 1

    async def test_allowed_and_admin_users_not_flagged(self, db_session: AsyncSession) -> None:
        org = await _seed_org(db_session)
        allowed_user = await _seed_member(db_session, org_id=org.id, role="member")
        await _seed_member(db_session, org_id=org.id, role="admin")

        connection, external_item, document = await _seed_connector_document(
            db_session, org_id=org.id
        )
        db_session.add(
            SourceAclMapping(
                organization_id=org.id,
                connector_connection_id=connection.id,
                source_type="connector_source_item",
                source_id=str(external_item.id),
                user_id=allowed_user.id,
                principal_type="user",
                principal_value=str(allowed_user.id),
                action="read_only",
                acl_effect="allow",
                is_active=True,
            )
        )
        await db_session.flush()

        collection = Collection(organization_id=org.id, name="Org Wide", access_policy="org_wide")
        db_session.add(collection)
        await db_session.flush()
        db_session.add(CollectionDocument(collection_id=collection.id, document_id=document.id))
        await db_session.flush()

        svc = ConflictDetectionService()
        await svc.scan(db_session, organization_id=org.id)

        items, _ = await ConflictsRepository().list_conflicts(
            db_session, organization_id=org.id, resource_type="document"
        )
        conflicts = [c for c in items if c.conflict_type == "collection_allow_connector_acl_deny"]
        assert conflicts == []

    async def test_idempotent_rescan(self, db_session: AsyncSession) -> None:
        org = await _seed_org(db_session)
        allowed_user = await _seed_member(db_session, org_id=org.id, role="member")
        await _seed_member(db_session, org_id=org.id, role="member")

        connection, external_item, document = await _seed_connector_document(
            db_session, org_id=org.id
        )
        db_session.add(
            SourceAclMapping(
                organization_id=org.id,
                connector_connection_id=connection.id,
                source_type="connector_source_item",
                source_id=str(external_item.id),
                user_id=allowed_user.id,
                principal_type="user",
                principal_value=str(allowed_user.id),
                action="read_only",
                acl_effect="allow",
                is_active=True,
            )
        )
        await db_session.flush()
        collection = Collection(organization_id=org.id, name="Org Wide", access_policy="org_wide")
        db_session.add(collection)
        await db_session.flush()
        db_session.add(CollectionDocument(collection_id=collection.id, document_id=document.id))
        await db_session.flush()

        svc = ConflictDetectionService()
        first = await svc.scan(db_session, organization_id=org.id)
        second = await svc.scan(db_session, organization_id=org.id)
        assert first.conflicts_created >= 1
        assert second.conflicts_created == 0


# ─── F354: citation_visible_source_hidden ──────────────────────────────────────


@pytest.mark.asyncio
class TestCitationVisibleSourceHidden:
    async def test_revoked_connector_connection_flags_citation(
        self, db_session: AsyncSession
    ) -> None:
        org = await _seed_org(db_session)
        citing_user = await _seed_member(db_session, org_id=org.id, role="member")
        _connection, _external_item, document = await _seed_connector_document(
            db_session, org_id=org.id, connection_status="revoked"
        )
        chunk = await _seed_document_chunk(db_session, document_id=document.id)

        session = ChatSession(organization_id=org.id, user_id=citing_user.id)
        db_session.add(session)
        await db_session.flush()
        message = ChatMessage(chat_session_id=session.id, role="assistant", content="Answer text")
        db_session.add(message)
        await db_session.flush()
        citation = Citation(
            chat_message_id=message.id,
            document_id=document.id,
            chunk_id=chunk.id,
            text_snippet="Cited text.",
        )
        db_session.add(citation)
        await db_session.flush()

        svc = ConflictDetectionService()
        await svc.scan(db_session, organization_id=org.id)

        items, _ = await ConflictsRepository().list_conflicts(
            db_session, organization_id=org.id, resource_type="citation"
        )
        conflicts = [c for c in items if c.conflict_type == "citation_visible_source_hidden"]
        assert len(conflicts) == 1
        assert conflicts[0].subject_value == str(citing_user.id)
        assert conflicts[0].resource_id == str(citation.id)
        assert conflicts[0].conflict_context_json["reason"] == "connector_revoked"

    async def test_explicit_deny_flags_citation_on_regular_document(
        self, db_session: AsyncSession
    ) -> None:
        org = await _seed_org(db_session)
        citing_user = await _seed_member(db_session, org_id=org.id, role="member")

        document = Document(
            organization_id=org.id,
            filename="upload.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key=f"documents/{uuid4().hex[:8]}.pdf",
            status="indexed",
        )
        db_session.add(document)
        await db_session.flush()
        chunk = await _seed_document_chunk(db_session, document_id=document.id)

        db_session.add(
            ResourceAccessDeny(
                organization_id=org.id,
                principal_type="user",
                principal_value=str(citing_user.id),
                user_id=citing_user.id,
                resource_type="document",
                resource_id=str(document.id),
                action="read_only",
                status="active",
            )
        )
        await db_session.flush()

        session = ChatSession(organization_id=org.id, user_id=citing_user.id)
        db_session.add(session)
        await db_session.flush()
        message = ChatMessage(chat_session_id=session.id, role="assistant", content="Answer text")
        db_session.add(message)
        await db_session.flush()
        citation = Citation(
            chat_message_id=message.id,
            document_id=document.id,
            chunk_id=chunk.id,
            text_snippet="Cited text.",
        )
        db_session.add(citation)
        await db_session.flush()

        svc = ConflictDetectionService()
        await svc.scan(db_session, organization_id=org.id)

        items, _ = await ConflictsRepository().list_conflicts(
            db_session, organization_id=org.id, resource_type="citation"
        )
        conflicts = [c for c in items if c.conflict_type == "citation_visible_source_hidden"]
        assert len(conflicts) == 1
        assert conflicts[0].conflict_context_json["reason"] == "explicit_deny"


# ─── F354: graph_entity_visible_evidence_inaccessible ──────────────────────────


@pytest.mark.asyncio
class TestGraphEntityVisibleEvidenceInaccessible:
    async def test_restricted_collection_document_flags_entity(
        self, db_session: AsyncSession
    ) -> None:
        org = await _seed_org(db_session)
        document = Document(
            organization_id=org.id,
            filename="restricted.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key=f"documents/{uuid4().hex[:8]}.pdf",
            status="indexed",
        )
        db_session.add(document)
        await db_session.flush()

        collection = Collection(
            organization_id=org.id, name="Restricted", access_policy="selected_members"
        )
        db_session.add(collection)
        await db_session.flush()
        db_session.add(CollectionDocument(collection_id=collection.id, document_id=document.id))
        await db_session.flush()

        with patch(
            "app.domains.permissions.services.conflict_detection_service._evidence_repo"
            ".list_entities_for_documents",
            new_callable=AsyncMock,
        ) as mock_entities:
            mock_entities.return_value = {str(document.id): ["entity-abc"]}
            svc = ConflictDetectionService()
            await svc.scan(db_session, organization_id=org.id)

        items, _ = await ConflictsRepository().list_conflicts(
            db_session, organization_id=org.id, resource_type="graph_entity"
        )
        conflicts = [
            c for c in items if c.conflict_type == "graph_entity_visible_evidence_inaccessible"
        ]
        assert len(conflicts) == 1
        assert conflicts[0].subject_type == "collection"
        assert conflicts[0].subject_value == str(collection.id)
        assert conflicts[0].resource_id == "entity-abc"

    async def test_org_wide_collection_not_flagged(self, db_session: AsyncSession) -> None:
        org = await _seed_org(db_session)
        document = Document(
            organization_id=org.id,
            filename="open.pdf",
            file_type="pdf",
            storage_bucket="documents",
            storage_object_key=f"documents/{uuid4().hex[:8]}.pdf",
            status="indexed",
        )
        db_session.add(document)
        await db_session.flush()

        collection = Collection(organization_id=org.id, name="Open", access_policy="org_wide")
        db_session.add(collection)
        await db_session.flush()
        db_session.add(CollectionDocument(collection_id=collection.id, document_id=document.id))
        await db_session.flush()

        with patch(
            "app.domains.permissions.services.conflict_detection_service._evidence_repo"
            ".list_entities_for_documents",
            new_callable=AsyncMock,
        ) as mock_entities:
            svc = ConflictDetectionService()
            await svc.scan(db_session, organization_id=org.id)
            mock_entities.assert_not_called()

        items, _ = await ConflictsRepository().list_conflicts(
            db_session, organization_id=org.id, resource_type="graph_entity"
        )
        assert items == []
