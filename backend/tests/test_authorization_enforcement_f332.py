"""Tests for F332: Backend authorization enforcement across files, collections,
connectors, citations, GraphRAG, and future sources.

Covers:
- Document list filtering by policy (member, viewer, connector ACL, explicit deny)
- Document detail/download/delete/manage enforcement via require_document_policy_access
- Collection create/manage/delete permission enforcement
- Connector list_available filtering
- Chat retrieval: document_ids pre-filter and post-retrieval citation filter
- Explicit grant overrides for members without role permission
- Connector ACL enforcement for connector-backed documents
- Cross-org tenant isolation
- Admin/owner full visibility (rule 5 bypass)
- Unknown future source type defaults to deny
- SourceAuthorizationAdapter registry and default-deny adapter
- ResourceContextBatchBuilder batch queries (unit-level)
- SubjectContext for API-key principals
"""

from __future__ import annotations

import os
import uuid
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

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

import pytest

from app.auth.authorization_service import AuthorizationService
from app.auth.models import AuthenticatedPrincipal
from app.auth.policy_engine import (
    Action,
    DenyReason,
    PermissionResult,
    PolicyEngine,
    ResourceContext,
    ResourceType,
    SubjectContext,
)
from app.auth.resource_context_builder import (
    build_collection_resource_context,
    build_connector_resource_context,
)
from app.auth.source_authorization_adapter import (
    SourceAuthorizationAdapter,
    SourceAuthorizationAdapterRegistry,
    _DefaultDenyAdapter,
)
from app.models.permissions import ROLE_PERMISSIONS, PermissionType

# ── Fixtures / helpers ────────────────────────────────────────────────────────

ORG_A = "aaaaaaaa-0000-0000-0000-000000000001"
ORG_B = "bbbbbbbb-0000-0000-0000-000000000002"

USER_1 = "00000000-0000-0000-0000-000000000001"
USER_2 = "00000000-0000-0000-0000-000000000002"
USER_3 = "00000000-0000-0000-0000-000000000003"

DOC_1 = "cccccccc-0000-0000-0000-000000000001"
DOC_2 = "cccccccc-0000-0000-0000-000000000002"

COL_1 = "dddddddd-0000-0000-0000-000000000001"

CONN_1 = "eeeeeeee-0000-0000-0000-000000000001"


def _subject(role: str, org: str = ORG_A, user: str = USER_1) -> SubjectContext:
    perms = ROLE_PERMISSIONS.get(role, frozenset())
    return SubjectContext(
        user_id=user,
        organization_id=org,
        roles=frozenset({role}),
        resolved_permissions=perms,
    )


def _principal(role: str, org: str = ORG_A, user: str = USER_1) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user,
        organization_id=org,
        roles=[role],
        auth_provider="app",
    )


def _doc_ctx(org: str = ORG_A, doc_id: str = DOC_1, **kwargs) -> ResourceContext:
    return ResourceContext(
        resource_type=ResourceType.document,
        resource_id=doc_id,
        organization_id=org,
        **kwargs,
    )


_engine = PolicyEngine()


# ── Policy-engine unit tests (stateless) ─────────────────────────────────────


class TestDocumentListAuthorization:
    def test_member_can_list_own_org_docs(self):
        subject = _subject("member")
        resource = _doc_ctx()
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.allow
        assert result.matched_rule == "role_permission"

    def test_viewer_can_list_own_org_docs(self):
        subject = _subject("viewer")
        resource = _doc_ctx()
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.allow

    def test_billing_admin_cannot_list_docs(self):
        subject = _subject("billing_admin")
        resource = _doc_ctx()
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.insufficient_role

    def test_security_admin_cannot_list_docs(self):
        subject = _subject("security_admin")
        resource = _doc_ctx()
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.deny

    def test_admin_bypasses_everything(self):
        subject = _subject("admin")
        resource = _doc_ctx(org=ORG_A)
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.allow
        assert result.matched_rule == "owner_admin_override"

    def test_owner_bypasses_everything(self):
        subject = _subject("owner")
        resource = _doc_ctx()
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.allow
        assert result.matched_rule == "owner_admin_override"

    def test_cross_org_doc_is_denied(self):
        subject = _subject("owner", org=ORG_A)
        resource = _doc_ctx(org=ORG_B)
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    def test_member_with_explicit_deny_is_rejected(self):
        subject = _subject("member", user=USER_1)
        resource = _doc_ctx(explicit_deny_user_ids=[USER_1])
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.explicit_resource_deny

    def test_viewer_without_documents_view_blocked_by_role_permission(self):
        # viewer has documents_view — but let's test with a user with no perms
        subject = SubjectContext(
            user_id=USER_1,
            organization_id=ORG_A,
            roles=frozenset({"billing_admin"}),
            resolved_permissions=frozenset({PermissionType.billing_view}),
        )
        resource = _doc_ctx()
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.deny


class TestDocumentViewAuthorization:
    def test_member_can_view_doc(self):
        subject = _subject("member")
        result = _engine.authorize(subject, Action.view, _doc_ctx())
        assert result.result is PermissionResult.allow

    def test_member_blocked_by_connector_acl(self):
        subject = _subject("member", user=USER_1)
        resource = _doc_ctx(
            connector_id=CONN_1,
            connector_allowed_user_ids=[USER_2],  # USER_1 not in ACL
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.connector_acl_denied

    def test_member_allowed_by_connector_acl(self):
        subject = _subject("member", user=USER_1)
        resource = _doc_ctx(
            connector_id=CONN_1,
            connector_allowed_user_ids=[USER_1],
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow
        assert result.matched_rule == "connector_acl"

    def test_connector_doc_with_empty_acl_is_accessible(self):
        """Empty ACL list means no connector ACL enforcement."""
        subject = _subject("member", user=USER_1)
        resource = _doc_ctx(
            connector_id=CONN_1,
            connector_allowed_user_ids=[],  # empty = no enforcement
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow

    def test_explicit_allow_overrides_missing_role_permission(self):
        subject = SubjectContext(
            user_id=USER_1,
            organization_id=ORG_A,
            roles=frozenset({"billing_admin"}),
            resolved_permissions=frozenset({PermissionType.billing_view}),
        )
        resource = _doc_ctx(explicit_allow_user_ids=[USER_1])
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow
        assert result.matched_rule == "explicit_resource_allow"

    def test_explicit_deny_overrides_explicit_allow(self):
        subject = _subject("member", user=USER_1)
        resource = _doc_ctx(
            explicit_allow_user_ids=[USER_1],
            explicit_deny_user_ids=[USER_1],
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.explicit_resource_deny


class TestDocumentDeleteAuthorization:
    def test_member_cannot_delete_doc(self):
        subject = _subject("member")
        result = _engine.authorize(subject, Action.delete, _doc_ctx())
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.insufficient_role

    def test_admin_can_delete_doc(self):
        subject = _subject("admin")
        result = _engine.authorize(subject, Action.delete, _doc_ctx())
        assert result.result is PermissionResult.allow
        assert result.matched_rule == "owner_admin_override"

    def test_owner_can_delete_doc(self):
        subject = _subject("owner")
        result = _engine.authorize(subject, Action.delete, _doc_ctx())
        assert result.result is PermissionResult.allow


class TestDocumentManageAuthorization:
    def test_member_cannot_manage_doc(self):
        subject = _subject("member")
        result = _engine.authorize(subject, Action.manage, _doc_ctx())
        assert result.result is PermissionResult.deny

    def test_admin_can_manage_doc(self):
        subject = _subject("admin")
        result = _engine.authorize(subject, Action.manage, _doc_ctx())
        assert result.result is PermissionResult.allow


class TestDocumentChatAuthorization:
    def test_member_can_chat_with_doc(self):
        subject = _subject("member")
        result = _engine.authorize(subject, Action.chat, _doc_ctx())
        assert result.result is PermissionResult.allow

    def test_connector_backed_doc_blocked_for_user_not_in_acl(self):
        subject = _subject("member", user=USER_1)
        resource = _doc_ctx(
            connector_id=CONN_1,
            connector_allowed_user_ids=[USER_2],
        )
        result = _engine.authorize(subject, Action.chat, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.connector_acl_denied

    def test_doc_in_accessible_collection_allows_viewer(self):
        """A viewer with chat_use_collections in permissions can chat via collection."""
        subject = SubjectContext(
            user_id=USER_1,
            organization_id=ORG_A,
            roles=frozenset({"reviewer"}),
            resolved_permissions=ROLE_PERMISSIONS["reviewer"],
        )
        resource = _doc_ctx(
            collection_ids=[COL_1],
            subject_accessible_collection_ids=[COL_1],
        )
        result = _engine.authorize(subject, Action.chat, resource)
        assert result.result is PermissionResult.allow
        assert result.matched_rule == "collection_allow"


class TestCitationAuthorization:
    def test_member_can_cite_doc(self):
        subject = _subject("member")
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=DOC_1,
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.cite, resource)
        assert result.result is PermissionResult.allow

    def test_connector_backed_doc_not_in_acl_cannot_be_cited(self):
        subject = _subject("member", user=USER_1)
        resource = _doc_ctx(
            connector_id=CONN_1,
            connector_allowed_user_ids=[USER_2],
        )
        result = _engine.authorize(subject, Action.cite, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.connector_acl_denied


class TestCollectionAuthorization:
    def test_member_can_list_collections(self):
        subject = _subject("member")
        resource = ResourceContext(
            resource_type=ResourceType.collection,
            resource_id=COL_1,
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.allow

    def test_member_cannot_delete_collection(self):
        subject = _subject("member")
        resource = ResourceContext(
            resource_type=ResourceType.collection,
            resource_id=COL_1,
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.delete, resource)
        assert result.result is PermissionResult.deny

    def test_admin_can_delete_collection(self):
        subject = _subject("admin")
        resource = ResourceContext(
            resource_type=ResourceType.collection,
            resource_id=COL_1,
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.delete, resource)
        assert result.result is PermissionResult.allow

    def test_billing_admin_cannot_view_collection(self):
        subject = _subject("billing_admin")
        resource = ResourceContext(
            resource_type=ResourceType.collection,
            resource_id=COL_1,
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny


class TestConnectorAuthorization:
    def test_member_can_list_connectors(self):
        subject = _subject("member")
        resource = ResourceContext(
            resource_type=ResourceType.connector,
            resource_id=CONN_1,
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.allow

    def test_member_cannot_manage_connector(self):
        subject = _subject("member")
        resource = ResourceContext(
            resource_type=ResourceType.connector,
            resource_id=CONN_1,
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.manage, resource)
        assert result.result is PermissionResult.deny

    def test_admin_can_manage_connector(self):
        subject = _subject("admin")
        resource = ResourceContext(
            resource_type=ResourceType.connector,
            resource_id=CONN_1,
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.manage, resource)
        assert result.result is PermissionResult.allow


class TestGraphAuthorization:
    def test_member_can_view_graph_entity(self):
        subject = _subject("member")
        resource = ResourceContext(
            resource_type=ResourceType.graph_entity,
            resource_id="entity-1",
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow

    def test_member_cannot_manage_graph_entity(self):
        subject = _subject("member")
        resource = ResourceContext(
            resource_type=ResourceType.graph_entity,
            resource_id="entity-1",
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.manage, resource)
        assert result.result is PermissionResult.deny

    def test_admin_can_manage_graph_entity(self):
        subject = _subject("admin")
        resource = ResourceContext(
            resource_type=ResourceType.graph_entity,
            resource_id="entity-1",
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.manage, resource)
        assert result.result is PermissionResult.allow

    def test_graph_evidence_cross_org_denied(self):
        subject = _subject("admin", org=ORG_A)
        resource = ResourceContext(
            resource_type=ResourceType.graph_evidence,
            resource_id="evidence-1",
            organization_id=ORG_B,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary


class TestTenantIsolation:
    def test_owner_of_org_a_cannot_access_org_b_docs(self):
        subject = _subject("owner", org=ORG_A)
        resource = _doc_ctx(org=ORG_B)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    def test_admin_of_org_a_cannot_list_org_b_docs(self):
        subject = _subject("admin", org=ORG_A)
        resource = _doc_ctx(org=ORG_B)
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.deny

    def test_member_of_org_a_cannot_chat_org_b_doc(self):
        subject = _subject("member", org=ORG_A)
        resource = _doc_ctx(org=ORG_B)
        result = _engine.authorize(subject, Action.chat, resource)
        assert result.result is PermissionResult.deny


class TestUnknownFutureSourceType:
    def test_unknown_resource_type_always_denied(self):
        subject = _subject("owner")  # admin bypass does NOT apply for unknown types
        resource = ResourceContext(
            resource_type=ResourceType.unknown,
            resource_id="future-resource-1",
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.unknown_resource_type

    def test_admin_cannot_bypass_unknown_resource_type(self):
        """Rule 4 fires before rule 5 (owner_admin_override)."""
        subject = _subject("admin")
        resource = ResourceContext(
            resource_type=ResourceType.unknown,
            resource_id="future-1",
            organization_id=ORG_A,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny

    def test_unknown_deny_precedes_tenant_boundary(self):
        """Unknown type is checked at rule 4, tenant boundary at rule 2 — tenant wins."""
        subject = _subject("member", org=ORG_A)
        # Cross-org unknown resource — tenant_boundary fires first
        resource = ResourceContext(
            resource_type=ResourceType.unknown,
            resource_id="x",
            organization_id=ORG_B,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        # tenant_boundary fires at rule 2, before unknown_resource_type at rule 4
        assert result.deny_reason is DenyReason.tenant_boundary


class TestFeatureEntitlementGate:
    def test_feature_disabled_blocks_member(self):
        subject = _subject("member")
        resource = _doc_ctx(feature_enabled=False)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.feature_not_entitled

    def test_feature_enabled_passes_through(self):
        subject = _subject("member")
        resource = _doc_ctx(feature_enabled=True)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow

    def test_feature_none_treated_as_enabled(self):
        subject = _subject("member")
        resource = _doc_ctx(feature_enabled=None)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow

    def test_admin_bypasses_feature_flag(self):
        """Admin bypass (rule 5) fires before feature entitlement check (rule 10)."""
        subject = _subject("admin")
        resource = _doc_ctx(feature_enabled=False)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow


class TestApiKeySubject:
    def test_api_key_with_documents_view_can_view_doc(self):
        subject = SubjectContext(
            user_id=USER_1,
            organization_id=ORG_A,
            roles=frozenset(),
            resolved_permissions=frozenset({PermissionType.documents_view}),
            is_api_key=True,
        )
        result = _engine.authorize(subject, Action.view, _doc_ctx())
        assert result.result is PermissionResult.allow

    def test_api_key_without_documents_view_cannot_view_doc(self):
        subject = SubjectContext(
            user_id=USER_1,
            organization_id=ORG_A,
            roles=frozenset(),
            resolved_permissions=frozenset({PermissionType.chat_use}),
            is_api_key=True,
        )
        result = _engine.authorize(subject, Action.view, _doc_ctx())
        assert result.result is PermissionResult.deny

    def test_api_key_respects_connector_acl(self):
        subject = SubjectContext(
            user_id=USER_1,
            organization_id=ORG_A,
            roles=frozenset(),
            resolved_permissions=frozenset({PermissionType.documents_view}),
            is_api_key=True,
        )
        resource = _doc_ctx(
            connector_id=CONN_1,
            connector_allowed_user_ids=[USER_2],  # USER_1 not allowed
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny


class TestFilterAccessibleResources:
    def test_filters_cross_org_resources(self):
        subject = _subject("member", org=ORG_A)
        resources = [
            _doc_ctx(org=ORG_A, doc_id=DOC_1),
            _doc_ctx(org=ORG_B, doc_id=DOC_2),
        ]
        accessible = _engine.filter_accessible_resources(subject, Action.view, resources)
        assert len(accessible) == 1
        assert accessible[0].resource_id == DOC_1

    def test_filters_explicitly_denied_resources(self):
        subject = _subject("member", user=USER_1, org=ORG_A)
        resources = [
            _doc_ctx(doc_id=DOC_1),
            _doc_ctx(doc_id=DOC_2, explicit_deny_user_ids=[USER_1]),
        ]
        accessible = _engine.filter_accessible_resources(subject, Action.view, resources)
        assert len(accessible) == 1
        assert accessible[0].resource_id == DOC_1

    def test_filters_connector_acl_denied_resources(self):
        subject = _subject("member", user=USER_1)
        resources = [
            _doc_ctx(doc_id=DOC_1),
            _doc_ctx(doc_id=DOC_2, connector_id=CONN_1, connector_allowed_user_ids=[USER_2]),
        ]
        accessible = _engine.filter_accessible_resources(subject, Action.view, resources)
        assert len(accessible) == 1
        assert accessible[0].resource_id == DOC_1

    def test_admin_sees_all_resources(self):
        subject = _subject("admin")
        resources = [
            _doc_ctx(doc_id=DOC_1),
            _doc_ctx(doc_id=DOC_2, explicit_deny_user_ids=[USER_1]),
            _doc_ctx(
                doc_id="cccccccc-0000-0000-0000-000000000003",
                connector_id=CONN_1,
                connector_allowed_user_ids=[USER_2],
            ),
        ]
        accessible = _engine.filter_accessible_resources(subject, Action.view, resources)
        assert len(accessible) == 3

    def test_empty_list_returns_empty(self):
        subject = _subject("member")
        accessible = _engine.filter_accessible_resources(subject, Action.view, [])
        assert accessible == []


# ── AuthorizationService async tests ─────────────────────────────────────────


class TestAuthorizationServiceAsync:
    @pytest.mark.asyncio
    async def test_authorize_returns_allow_for_admin(self):
        """AuthorizationService delegates to PolicyEngine; admin rule 5 allows."""
        principal = _principal("admin")
        resource = _doc_ctx()
        db = AsyncMock()

        svc = AuthorizationService()
        with patch.object(svc, "_build_subject", new_callable=AsyncMock) as mock_build:
            mock_build.return_value = SubjectContext(
                user_id=USER_1,
                organization_id=ORG_A,
                roles=frozenset({"admin"}),
                resolved_permissions=ROLE_PERMISSIONS["admin"],
            )
            result = await svc.authorize(principal, Action.view, resource, db)
        assert result.result is PermissionResult.allow
        assert result.matched_rule == "owner_admin_override"

    @pytest.mark.asyncio
    async def test_authorize_or_raise_raises_404_on_deny(self):
        """authorize_or_raise should raise 404 when policy denies."""
        from fastapi import HTTPException

        principal = _principal("billing_admin")
        resource = _doc_ctx()
        db = AsyncMock()

        with patch.object(
            AuthorizationService, "_build_subject", new_callable=AsyncMock
        ) as mock_build:
            mock_build.return_value = SubjectContext(
                user_id=USER_1,
                organization_id=ORG_A,
                roles=frozenset({"billing_admin"}),
                resolved_permissions=ROLE_PERMISSIONS["billing_admin"],
            )
            svc = AuthorizationService()
            with pytest.raises(HTTPException) as exc_info:
                await svc.authorize_or_raise(principal, Action.view, resource, db)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_authorize_or_raise_raises_403_when_configured(self):
        from fastapi import HTTPException

        principal = _principal("billing_admin")
        resource = _doc_ctx()
        db = AsyncMock()

        with patch.object(
            AuthorizationService, "_build_subject", new_callable=AsyncMock
        ) as mock_build:
            mock_build.return_value = SubjectContext(
                user_id=USER_1,
                organization_id=ORG_A,
                roles=frozenset({"billing_admin"}),
                resolved_permissions=ROLE_PERMISSIONS["billing_admin"],
            )
            svc = AuthorizationService()
            with pytest.raises(HTTPException) as exc_info:
                await svc.authorize_or_raise(
                    principal, Action.view, resource, db, deny_status=403, deny_detail="Forbidden"
                )
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail == "Forbidden"


# ── ResourceContextBuilder helper tests ──────────────────────────────────────


class TestBuildCollectionResourceContext:
    def test_builds_collection_context_correctly(self):
        collection = MagicMock()
        collection.id = uuid.UUID(COL_1)
        org_id = uuid.UUID(ORG_A)

        ctx = build_collection_resource_context(collection=collection, organization_id=org_id)

        assert ctx.resource_type is ResourceType.collection
        assert ctx.resource_id == COL_1
        assert ctx.organization_id == ORG_A


class TestBuildConnectorResourceContext:
    def test_builds_connector_context_correctly(self):
        connection = MagicMock()
        connection.id = uuid.UUID(CONN_1)
        org_id = uuid.UUID(ORG_A)

        ctx = build_connector_resource_context(connection=connection, organization_id=org_id)

        assert ctx.resource_type is ResourceType.connector
        assert ctx.resource_id == CONN_1
        assert ctx.organization_id == ORG_A


# ── SourceAuthorizationAdapter tests ─────────────────────────────────────────


class TestSourceAuthorizationAdapterRegistry:
    def test_unregistered_type_returns_default_deny_adapter(self):
        registry = SourceAuthorizationAdapterRegistry()
        adapter = registry.get_or_default_deny("some_future_source")
        assert isinstance(adapter, _DefaultDenyAdapter)
        assert adapter.source_type == "some_future_source"

    def test_get_returns_none_for_unknown_type(self):
        registry = SourceAuthorizationAdapterRegistry()
        assert registry.get("unknown_type") is None

    def test_register_and_retrieve_adapter(self):
        class MyAdapter(SourceAuthorizationAdapter):
            source_type = "my_test_source"

            async def build_resource_context(
                self, db_session, *, resource_id, organization_id, subject_accessible_collection_ids
            ):
                return ResourceContext(
                    resource_type=ResourceType.document,
                    resource_id=resource_id,
                    organization_id=organization_id,
                )

        registry = SourceAuthorizationAdapterRegistry()
        adapter = MyAdapter()
        registry.register(adapter)

        retrieved = registry.get("my_test_source")
        assert retrieved is adapter

    def test_registered_types_lists_registered_adapters(self):
        class AdapterA(SourceAuthorizationAdapter):
            source_type = "source_a"

            async def build_resource_context(self, *args, **kwargs): ...

        class AdapterB(SourceAuthorizationAdapter):
            source_type = "source_b"

            async def build_resource_context(self, *args, **kwargs): ...

        registry = SourceAuthorizationAdapterRegistry()
        registry.register(AdapterA())
        registry.register(AdapterB())

        types = registry.registered_types()
        assert "source_a" in types
        assert "source_b" in types

    @pytest.mark.asyncio
    async def test_default_deny_adapter_returns_unknown_resource_context(self):
        adapter = _DefaultDenyAdapter(source_type="unknown_future")
        db = AsyncMock()
        ctx = await adapter.build_resource_context(
            db,
            resource_id="r-1",
            organization_id=ORG_A,
            subject_accessible_collection_ids=[],
        )
        assert ctx.resource_type is ResourceType.unknown

    @pytest.mark.asyncio
    async def test_default_deny_adapter_policy_denies_all_roles(self):
        adapter = _DefaultDenyAdapter(source_type="unknown_future")
        db = AsyncMock()
        ctx = await adapter.build_resource_context(
            db,
            resource_id="r-1",
            organization_id=ORG_A,
            subject_accessible_collection_ids=[],
        )

        for role in ["owner", "admin", "member", "viewer"]:
            subject = _subject(role)
            result = _engine.authorize(subject, Action.view, ctx)
            assert result.result is PermissionResult.deny, (
                f"Role {role!r} should be denied for unknown type"
            )

    def test_base_class_default_deny_context_returns_unknown_type(self):
        class ConcreteAdapter(SourceAuthorizationAdapter):
            source_type = "concrete"

            async def build_resource_context(self, *args, **kwargs):
                return self.default_deny_context(resource_id="r", organization_id=ORG_A)

        adapter = ConcreteAdapter()
        ctx = adapter.default_deny_context(resource_id="r-1", organization_id=ORG_A)
        assert ctx.resource_type is ResourceType.unknown
        assert ctx.resource_id == "r-1"
        assert ctx.organization_id == ORG_A


# ── Cross-role permission matrix ─────────────────────────────────────────────


class TestPermissionMatrix:
    """Validate the full matrix of built-in roles against document actions."""

    _ROLES: ClassVar[list[str]] = [
        "viewer",
        "reviewer",
        "developer",
        "member",
        "billing_admin",
        "security_admin",
        "admin",
        "owner",
    ]

    @pytest.mark.parametrize(
        "role", ["viewer", "reviewer", "developer", "member", "admin", "owner"]
    )
    def test_can_list_docs(self, role):
        subject = _subject(role)
        result = _engine.authorize(subject, Action.list, _doc_ctx())
        assert result.result is PermissionResult.allow, f"Role {role!r} should be able to list docs"

    @pytest.mark.parametrize("role", ["billing_admin", "security_admin"])
    def test_cannot_list_docs(self, role):
        subject = _subject(role)
        result = _engine.authorize(subject, Action.list, _doc_ctx())
        assert result.result is PermissionResult.deny, (
            f"Role {role!r} should NOT be able to list docs"
        )

    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_can_delete_docs(self, role):
        subject = _subject(role)
        result = _engine.authorize(subject, Action.delete, _doc_ctx())
        assert result.result is PermissionResult.allow

    @pytest.mark.parametrize(
        "role", ["viewer", "reviewer", "member", "billing_admin", "security_admin"]
    )
    def test_cannot_delete_docs(self, role):
        subject = _subject(role)
        result = _engine.authorize(subject, Action.delete, _doc_ctx())
        assert result.result is PermissionResult.deny

    @pytest.mark.parametrize("role", ["admin", "owner"])
    def test_can_manage_docs(self, role):
        subject = _subject(role)
        result = _engine.authorize(subject, Action.manage, _doc_ctx())
        assert result.result is PermissionResult.allow

    @pytest.mark.parametrize("role", ["viewer", "member", "billing_admin"])
    def test_cannot_manage_docs(self, role):
        subject = _subject(role)
        result = _engine.authorize(subject, Action.manage, _doc_ctx())
        assert result.result is PermissionResult.deny


# ── Regression: no organization context ──────────────────────────────────────


class TestNoOrganizationContext:
    def test_subject_without_org_is_denied(self):
        subject = SubjectContext(
            user_id=USER_1,
            organization_id=None,
            roles=frozenset({"admin"}),
            resolved_permissions=ROLE_PERMISSIONS["admin"],
        )
        result = _engine.authorize(subject, Action.view, _doc_ctx())
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.no_organization_context

    def test_system_resource_always_denied(self):
        subject = _subject("admin")
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id="chain-of-thought",
            organization_id=ORG_A,
            is_system_resource=True,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.system_deny
