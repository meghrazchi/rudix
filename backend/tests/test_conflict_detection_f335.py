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
from unittest.mock import patch
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

from app.domains.permissions.repositories.conflicts import ConflictsRepository
from app.domains.permissions.schemas.conflicts import (
    CONFLICT_TYPES,
    DB_TO_SEVERITY,
    SEVERITY_TO_DB,
    remediation_for,
)
from app.domains.permissions.services.conflict_detection_service import ConflictDetectionService
from app.models.authorization import ResourceAccessDeny, ResourceAccessGrant

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
