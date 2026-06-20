"""F336: Tenant-isolation regression suite.

pytest.mark.isolation — all tests verify that org A principals cannot
access org B resources regardless of role, explicit grants, or connector ACLs.

Covers: documents, collections, connectors, citations, graph entities,
evaluations, saved answers, connector_source_items, and unknown future types.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

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

from app.auth.policy_engine import (
    Action,
    DenyReason,
    PermissionResult,
    PolicyEngine,
    ResourceContext,
    ResourceType,
    SubjectContext,
)

pytestmark = pytest.mark.isolation

_engine = PolicyEngine()


def _org() -> str:
    return str(uuid4())


def _subject(
    org_id: str,
    roles: frozenset[str] = frozenset({"member"}),
    grants: list[tuple[ResourceType, str, Action]] | None = None,
) -> SubjectContext:
    return SubjectContext(
        user_id=str(uuid4()),
        organization_id=org_id,
        roles=roles,
        resource_grants=grants or [],
        resource_denies=[],
        accessible_collection_ids=frozenset(),
        connector_acl_item_ids=frozenset(),
        resolved_permissions=frozenset(),
    )


def _resource(
    rtype: ResourceType,
    org_id: str,
    resource_id: str | None = None,
) -> ResourceContext:
    return ResourceContext(
        resource_type=rtype,
        resource_id=resource_id or str(uuid4()),
        organization_id=org_id,
        owner_ids=frozenset(),
        collection_ids=frozenset(),
        connector_id=None,
        feature_enabled=True,
    )


# ─── document isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDocumentTenantIsolation:
    async def test_owner_of_org_a_denied_org_b_document(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"owner"}))
        resource = _resource(ResourceType.document, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_admin_of_org_a_denied_org_b_document(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"admin"}))
        resource = _resource(ResourceType.document, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_explicit_grant_cannot_cross_tenant(self) -> None:
        org_a = _org()
        org_b = _org()
        doc_id = str(uuid4())
        # Give subject an explicit grant on a resource that "looks" like org_b doc
        subject = _subject(
            org_a,
            grants=[(ResourceType.document, doc_id, Action.view)],
        )
        resource = _resource(ResourceType.document, org_b, doc_id)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_tenant_check_fires_before_resource_deny(self) -> None:
        org_a = _org()
        org_b = _org()
        doc_id = str(uuid4())
        subject = _subject(org_a, roles=frozenset({"owner"}))
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=doc_id,
            organization_id=org_b,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
            explicit_denies=[(str(uuid4()), Action.view)],
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.deny_reason is DenyReason.tenant_boundary


# ─── collection isolation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCollectionTenantIsolation:
    async def test_member_of_org_a_denied_org_b_collection(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"member"}))
        resource = _resource(ResourceType.collection, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_collection_membership_grant_does_not_cross_tenant(self) -> None:
        org_a = _org()
        org_b = _org()
        coll_id = str(uuid4())
        # subject has accessible_collection_ids containing the collection ID
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org_a,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[],
            accessible_collection_ids=frozenset({coll_id}),
            connector_acl_item_ids=frozenset(),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=str(uuid4()),
            organization_id=org_b,
            owner_ids=frozenset(),
            collection_ids=frozenset({coll_id}),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary


# ─── connector isolation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestConnectorTenantIsolation:
    async def test_member_of_org_a_denied_org_b_connector(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"member"}))
        resource = _resource(ResourceType.connector, org_b)
        result = _engine.authorize(subject, Action.list, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_connector_acl_does_not_cross_tenant(self) -> None:
        org_a = _org()
        org_b = _org()
        item_id = str(uuid4())
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org_a,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset({item_id}),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.connector_source_item,
            resource_id=item_id,
            organization_id=org_b,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=str(uuid4()),
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary


# ─── citation isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCitationTenantIsolation:
    async def test_member_of_org_a_denied_org_b_citation(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"member"}))
        resource = _resource(ResourceType.citation, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_admin_of_org_a_denied_org_b_citation(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"admin"}))
        resource = _resource(ResourceType.citation, org_b)
        result = _engine.authorize(subject, Action.cite, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary


# ─── graph entity and evidence isolation ─────────────────────────────────────


@pytest.mark.asyncio
class TestGraphTenantIsolation:
    async def test_member_of_org_a_denied_org_b_graph_entity(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"member"}))
        resource = _resource(ResourceType.graph_entity, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_admin_of_org_a_denied_org_b_graph_evidence(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"admin"}))
        resource = _resource(ResourceType.graph_evidence, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary


# ─── evaluation and saved-answer isolation ────────────────────────────────────


@pytest.mark.asyncio
class TestEvaluationTenantIsolation:
    async def test_member_denied_org_b_evaluation(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"member"}))
        resource = _resource(ResourceType.evaluation, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_member_denied_org_b_saved_answer(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"member"}))
        resource = _resource(ResourceType.saved_answer, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary


# ─── future / unknown resource type isolation ─────────────────────────────────


@pytest.mark.asyncio
class TestUnknownResourceTenantIsolation:
    async def test_owner_denied_cross_tenant_unknown_resource(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"owner"}))
        resource = _resource(ResourceType.unknown, org_b)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        # tenant_boundary fires before unknown_resource_type
        assert result.deny_reason is DenyReason.tenant_boundary

    async def test_unknown_resource_same_tenant_still_denied(self) -> None:
        org_id = _org()
        subject = _subject(org_id, roles=frozenset({"owner"}))
        resource = _resource(ResourceType.unknown, org_id)
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.unknown_resource_type


# ─── no-organization-context isolation ───────────────────────────────────────


@pytest.mark.asyncio
class TestNoOrganizationContext:
    async def test_subject_without_org_is_denied_all_resources(self) -> None:
        any_org = _org()
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=None,
            roles=frozenset({"owner"}),
            resource_grants=[],
            resource_denies=[],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset(),
            resolved_permissions=frozenset(),
        )
        for rtype in (ResourceType.document, ResourceType.collection, ResourceType.connector):
            resource = _resource(rtype, any_org)
            result = _engine.authorize(subject, Action.view, resource)
            assert result.result is PermissionResult.deny
            assert result.deny_reason is DenyReason.no_organization_context

    async def test_filter_accessible_resources_removes_cross_tenant(self) -> None:
        org_a = _org()
        org_b = _org()
        subject = _subject(org_a, roles=frozenset({"owner"}))
        resources = [
            _resource(ResourceType.document, org_a),
            _resource(ResourceType.document, org_b),
            _resource(ResourceType.document, org_a),
        ]
        visible = _engine.filter_accessible_resources(subject, Action.view, resources)
        assert len(visible) == 2
        assert all(r.organization_id == org_a for r in visible)
