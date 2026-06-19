"""F336: Feature flag, rollout guard, monitoring, and seed-data validation tests.

Covers:
- authorization_enforcement feature flag in FeatureFlagService and _SETTINGS_ATTR
- ALL_FLAG_NAMES tuple includes authorization_enforcement
- Soft mode: when feature_enable_authorization_enforcement=False, deny decisions
  produce log events but the dependency still returns the document.
- log_authorization_event() emits structlog events with required fields.
- config.settings exposes feature_enable_authorization_enforcement.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import structlog

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


# ─── feature flag schema / catalogue ─────────────────────────────────────────


class TestFeatureFlagCatalogue:
    def test_authorization_enforcement_in_all_flag_names(self) -> None:
        from app.domains.admin.schemas.feature_flags import ALL_FLAG_NAMES

        assert "authorization_enforcement" in ALL_FLAG_NAMES

    def test_authorization_enforcement_is_valid_flag_name_literal(self) -> None:
        from app.domains.admin.schemas.feature_flags import FeatureFlagName

        args = FeatureFlagName.__args__  # type: ignore[attr-defined]
        assert "authorization_enforcement" in args

    def test_settings_attr_maps_authorization_enforcement(self) -> None:
        from app.domains.admin.services.feature_flag_service import _SETTINGS_ATTR

        assert "authorization_enforcement" in _SETTINGS_ATTR
        assert _SETTINGS_ATTR["authorization_enforcement"] == "feature_enable_authorization_enforcement"

    def test_settings_has_feature_enable_authorization_enforcement(self) -> None:
        from app.core.config import settings

        assert hasattr(settings, "feature_enable_authorization_enforcement")

    def test_default_value_is_true_for_strict_mode(self) -> None:
        from app.core.config import Settings

        s = Settings(
            database_url="postgresql+asyncpg://x:y@localhost/z",
            qdrant_url="http://localhost:6333",
            minio_endpoint="http://localhost:9000",
            minio_access_key="a",
            minio_secret_key="b",
            openai_api_key="sk-test",
            app_auth_secret="s3cr3t",
        )
        assert s.feature_enable_authorization_enforcement is True


# ─── settings env resolution ─────────────────────────────────────────────────


class TestFeatureFlagEnvResolution:
    def test_env_default_resolved_for_authorization_enforcement(self) -> None:
        from app.domains.admin.services.feature_flag_service import _env_default

        # Must resolve without KeyError (flag is registered in _SETTINGS_ATTR)
        val = _env_default("authorization_enforcement")
        assert isinstance(val, bool)

    def test_unknown_flag_returns_false(self) -> None:
        from app.domains.admin.services.feature_flag_service import _env_default

        assert _env_default("non_existent_flag_xyz") is False


# ─── log_authorization_event() ───────────────────────────────────────────────


class TestLogAuthorizationEvent:
    def test_log_authorization_event_exported(self) -> None:
        from app.core.logging import log_authorization_event

        assert callable(log_authorization_event)

    def test_log_authorization_event_emits_structlog_record(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        import structlog.testing

        from app.core.logging import log_authorization_event

        with structlog.testing.capture_logs() as cap:
            log_authorization_event(
                event="authorization_denied",
                organization_id="org-1",
                user_id="user-1",
                resource_type="document",
                resource_id="doc-1",
                action="view",
                decision="deny",
                deny_reason="insufficient_role",
                matched_rule="role_permission",
                request_id="req-1",
            )

        assert len(cap) >= 1
        entry = cap[-1]
        assert entry["event"] == "authorization_denied"
        assert entry.get("organization_id") == "org-1"
        assert entry.get("decision") == "deny"
        assert entry.get("deny_reason") == "insufficient_role"
        assert entry.get("matched_rule") == "role_permission"
        assert entry.get("request_id") == "req-1"

    def test_log_authorization_event_does_not_leak_sensitive_fields(self) -> None:
        import structlog.testing

        from app.core.logging import log_authorization_event

        with structlog.testing.capture_logs() as cap:
            log_authorization_event(
                event="authorization_granted",
                organization_id="org-1",
                user_id="user-1",
                resource_type="document",
                resource_id="doc-1",
                action="view",
                decision="allow",
                matched_rule="owner_admin_override",
            )

        entry = cap[-1]
        serialized = str(entry)
        for forbidden in ("sk-", "api_key=", "password=", "secret=", "token="):
            assert forbidden not in serialized.lower()

    def test_log_authorization_event_allow(self) -> None:
        import structlog.testing

        from app.core.logging import log_authorization_event

        with structlog.testing.capture_logs() as cap:
            log_authorization_event(
                event="authorization_granted",
                organization_id="org-x",
                user_id="user-x",
                resource_type="collection",
                action="list",
                decision="allow",
                matched_rule="role_permission",
            )
        assert cap[-1]["decision"] == "allow"
        assert cap[-1]["deny_reason"] is None


# ─── soft mode (canary rollout) ───────────────────────────────────────────────


class TestSoftModeRollout:
    """When feature_enable_authorization_enforcement=False the dependency logs
    the denial but does not raise — the document is returned to the caller."""

    @pytest.mark.asyncio
    async def test_soft_mode_returns_document_on_deny(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch
        from uuid import UUID

        from app.auth.policy_engine import (
            Action,
            AuthorizationResult,
            DenyReason,
            PermissionResult,
            ResourceType,
        )
        from app.core.config import settings

        monkeypatch.setattr(settings, "feature_enable_authorization_enforcement", False)

        # Build a minimal denied result
        deny_result = AuthorizationResult(
            result=PermissionResult.deny,
            deny_reason=DenyReason.insufficient_role,
            matched_rule="role_permission",
            trace=["role_permission:deny(insufficient_role)"],
            request_id="req-soft",
            subject_id="user-soft",
            organization_id="org-soft",
            resource_type=ResourceType.document,
            resource_id="doc-soft",
            action=Action.view,
        )

        mock_auth_svc = AsyncMock()
        mock_auth_svc.authorize.return_value = deny_result

        fake_doc = MagicMock()
        fake_doc.id = UUID("00000000-0000-0000-0000-000000000001")
        fake_doc.organization_id = UUID("00000000-0000-0000-0000-000000000002")

        mock_doc_repo = AsyncMock()
        mock_doc_repo.get_document.return_value = fake_doc

        from app.auth import dependencies as deps

        with (
            patch.object(deps, "_authorization_service", mock_auth_svc),
            patch.object(deps, "_document_repository", mock_doc_repo),
        ):
            factory = deps.require_document_policy_access(Action.view)

            principal = MagicMock()
            principal.user_id = "user-soft"
            principal.organization_id = "00000000-0000-0000-0000-000000000002"
            principal.roles = frozenset({"member"})
            principal.api_key_permissions = None

            mock_db = AsyncMock()
            mock_get_accessible_ids = AsyncMock(return_value=frozenset())
            mock_build_resource = AsyncMock(
                return_value=MagicMock(
                    resource_type=ResourceType.document,
                    resource_id="doc-soft",
                    organization_id="00000000-0000-0000-0000-000000000002",
                    owner_ids=frozenset(),
                    collection_ids=frozenset(),
                    connector_id=None,
                    feature_enabled=True,
                    explicit_denies=[],
                )
            )

            with (
                patch(
                    "app.auth.dependencies.get_subject_accessible_collection_ids",
                    mock_get_accessible_ids,
                ),
                patch(
                    "app.auth.dependencies.build_document_resource_context",
                    mock_build_resource,
                ),
            ):
                doc = await factory(
                    document_id="00000000-0000-0000-0000-000000000001",
                    principal=principal,
                    db_session=mock_db,
                )

        assert doc is fake_doc, "Soft mode should return the document even on deny"

    @pytest.mark.asyncio
    async def test_strict_mode_raises_on_deny(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch
        from uuid import UUID

        from fastapi import HTTPException

        from app.auth.policy_engine import (
            Action,
            AuthorizationResult,
            DenyReason,
            PermissionResult,
            ResourceType,
        )
        from app.core.config import settings

        monkeypatch.setattr(settings, "feature_enable_authorization_enforcement", True)

        deny_result = AuthorizationResult(
            result=PermissionResult.deny,
            deny_reason=DenyReason.insufficient_role,
            matched_rule="role_permission",
            trace=["role_permission:deny(insufficient_role)"],
            request_id="req-strict",
            subject_id="user-strict",
            organization_id="org-strict",
            resource_type=ResourceType.document,
            resource_id="doc-strict",
            action=Action.view,
        )

        mock_auth_svc = AsyncMock()
        mock_auth_svc.authorize.return_value = deny_result

        fake_doc = MagicMock()
        fake_doc.id = UUID("00000000-0000-0000-0000-000000000003")
        fake_doc.organization_id = UUID("00000000-0000-0000-0000-000000000004")

        mock_doc_repo = AsyncMock()
        mock_doc_repo.get_document.return_value = fake_doc

        from app.auth import dependencies as deps

        with (
            patch.object(deps, "_authorization_service", mock_auth_svc),
            patch.object(deps, "_document_repository", mock_doc_repo),
        ):
            factory = deps.require_document_policy_access(Action.view)

            principal = MagicMock()
            principal.user_id = "user-strict"
            principal.organization_id = "00000000-0000-0000-0000-000000000004"
            principal.roles = frozenset({"member"})
            principal.api_key_permissions = None

            mock_db = AsyncMock()
            mock_get_accessible_ids = AsyncMock(return_value=frozenset())
            mock_build_resource = AsyncMock(
                return_value=MagicMock(
                    resource_type=ResourceType.document,
                    resource_id="doc-strict",
                    organization_id="00000000-0000-0000-0000-000000000004",
                    owner_ids=frozenset(),
                    collection_ids=frozenset(),
                    connector_id=None,
                    feature_enabled=True,
                    explicit_denies=[],
                )
            )

            with (
                patch(
                    "app.auth.dependencies.get_subject_accessible_collection_ids",
                    mock_get_accessible_ids,
                ),
                patch(
                    "app.auth.dependencies.build_document_resource_context",
                    mock_build_resource,
                ),
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await factory(
                        document_id="00000000-0000-0000-0000-000000000003",
                        principal=principal,
                        db_session=mock_db,
                    )

        assert exc_info.value.status_code == 404


# ─── seed data / schema integrity ────────────────────────────────────────────


class TestSchemaAndSeedIntegrity:
    def test_authorization_conflict_table_is_in_metadata(self) -> None:
        from app.db.base import Base

        table_names = set(Base.metadata.tables.keys())
        assert "authorization_conflicts" in table_names

    def test_resource_access_grants_table_exists(self) -> None:
        from app.db.base import Base

        table_names = set(Base.metadata.tables.keys())
        assert "resource_access_grants" in table_names

    def test_resource_access_denies_table_exists(self) -> None:
        from app.db.base import Base

        table_names = set(Base.metadata.tables.keys())
        assert "resource_access_denies" in table_names

    def test_authorization_decision_log_table_exists(self) -> None:
        from app.db.base import Base

        table_names = set(Base.metadata.tables.keys())
        assert "authorization_decision_log" in table_names

    def test_org_feature_flag_overrides_table_exists(self) -> None:
        from app.db.base import Base

        table_names = set(Base.metadata.tables.keys())
        assert "org_feature_flag_overrides" in table_names

    def test_authorization_conflict_model_has_severity_constraint(self) -> None:
        from sqlalchemy import inspect as sa_inspect

        from app.db.base import Base

        table = Base.metadata.tables.get("authorization_conflicts")
        assert table is not None
        constraint_names = {c.name for c in table.constraints}
        # The severity check constraint was created in the F331 migration
        severity_constraints = [
            c for c in constraint_names if "severity" in (c or "").lower()
        ]
        assert len(severity_constraints) >= 1 or any(
            "check" in type(c).__name__.lower() for c in table.constraints
        )

    def test_authorization_conflict_status_values(self) -> None:
        from app.models.permissions import AuthorizationConflict

        valid_statuses = {"open", "investigating", "resolved", "dismissed"}
        # Model must be importable and have status mapped_column
        assert hasattr(AuthorizationConflict, "status")
        # Derive allowed values from the DB CheckConstraint name pattern
        # (exact check depends on SQLAlchemy internals, so we verify at service level)
        from app.domains.permissions.schemas.conflicts import CONFLICT_STATUSES

        assert set(CONFLICT_STATUSES) == valid_statuses
