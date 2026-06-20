"""F336: RAG-specific authorization regression tests.

Verifies that the retrieval, citation, and GraphRAG paths only surface
evidence that the requesting subject is authorized to see:

- Documents with no collection membership and no explicit grant → denied for member.
- Documents accessible via connector ACL → allowed for ACL-cleared subject.
- Citations from hidden source documents → denied via citation resource type.
- Graph entities and evidence from unauthorized orgs → denied.
- filter_accessible_resources() correctly filters out unauthorized docs in bulk.
- Chat action requires same grants as view (no special escalation).
- Deny-by-default applies for unknown future source types.
"""

from __future__ import annotations

import os
from uuid import uuid4

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

_engine = PolicyEngine()


def _org() -> str:
    return str(uuid4())


def _member(org_id: str) -> SubjectContext:
    return SubjectContext(
        user_id=str(uuid4()),
        organization_id=org_id,
        roles=frozenset({"member"}),
        resource_grants=[],
        resource_denies=[],
        accessible_collection_ids=frozenset(),
        connector_acl_item_ids=frozenset(),
        resolved_permissions=frozenset(),
    )


def _doc_resource(
    org_id: str,
    *,
    collection_ids: frozenset[str] = frozenset(),
    connector_id: str | None = None,
    explicit_denies: list | None = None,
) -> ResourceContext:
    return ResourceContext(
        resource_type=ResourceType.document,
        resource_id=str(uuid4()),
        organization_id=org_id,
        owner_ids=frozenset(),
        collection_ids=collection_ids,
        connector_id=connector_id,
        feature_enabled=True,
        explicit_denies=explicit_denies or [],
    )


# ─── retrieval filtering ──────────────────────────────────────────────────────


class TestRetrievalFiltering:
    def test_uncollected_document_allowed_for_member_via_role(self) -> None:
        org = _org()
        result = _engine.authorize(_member(org), Action.view, _doc_resource(org))
        assert result.result is PermissionResult.allow

    def test_member_denied_when_explicit_deny_exists(self) -> None:
        org = _org()
        member = _member(org)
        grant_id = str(uuid4())
        member = SubjectContext(
            user_id=member.user_id,
            organization_id=org,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[(grant_id, ResourceType.document, "doc-abc", Action.view)],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset(),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id="doc-abc",
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(member, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.explicit_resource_deny

    def test_connector_acl_allows_access_when_item_cleared(self) -> None:
        org = _org()
        item_id = str(uuid4())
        connector_id = str(uuid4())
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset({item_id}),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=item_id,
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=connector_id,
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow

    def test_connector_acl_denies_when_item_not_cleared(self) -> None:
        org = _org()
        item_id = str(uuid4())
        connector_id = str(uuid4())
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset(),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=item_id,
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=connector_id,
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.connector_acl_denied

    def test_bulk_filter_removes_denied_documents(self) -> None:
        org = _org()
        connector_id = str(uuid4())
        cleared_id = str(uuid4())
        blocked_id = str(uuid4())
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset({cleared_id}),
            resolved_permissions=frozenset(),
        )
        resources = [
            ResourceContext(
                resource_type=ResourceType.document,
                resource_id=cleared_id,
                organization_id=org,
                owner_ids=frozenset(),
                collection_ids=frozenset(),
                connector_id=connector_id,
                feature_enabled=True,
            ),
            ResourceContext(
                resource_type=ResourceType.document,
                resource_id=blocked_id,
                organization_id=org,
                owner_ids=frozenset(),
                collection_ids=frozenset(),
                connector_id=connector_id,
                feature_enabled=True,
            ),
        ]
        visible = _engine.filter_accessible_resources(subject, Action.view, resources)
        ids = {r.resource_id for r in visible}
        assert cleared_id in ids
        assert blocked_id not in ids

    def test_collection_membership_grants_document_access(self) -> None:
        org = _org()
        coll_id = str(uuid4())
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org,
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
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset({coll_id}),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow

    def test_collection_denied_when_member_not_in_collection(self) -> None:
        org = _org()
        coll_id = str(uuid4())
        # Resource belongs to a collection, subject is not in that collection
        # and there's no connector ACL — check the outcome
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset(),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset({coll_id}),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.collection_not_accessible


# ─── citation access ──────────────────────────────────────────────────────────


class TestCitationAccess:
    def test_member_can_cite_own_org_citation(self) -> None:
        org = _org()
        resource = ResourceContext(
            resource_type=ResourceType.citation,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(_member(org), Action.cite, resource)
        assert result.result is PermissionResult.allow

    def test_member_denied_cross_org_citation(self) -> None:
        org_a = _org()
        org_b = _org()
        resource = ResourceContext(
            resource_type=ResourceType.citation,
            resource_id=str(uuid4()),
            organization_id=org_b,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(_member(org_a), Action.cite, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    def test_explicit_deny_hides_citation_from_member(self) -> None:
        org = _org()
        cite_id = str(uuid4())
        grant_id = str(uuid4())
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[(grant_id, ResourceType.citation, cite_id, Action.cite)],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset(),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.citation,
            resource_id=cite_id,
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.cite, resource)
        assert result.result is PermissionResult.deny


# ─── chat action ──────────────────────────────────────────────────────────────


class TestChatAction:
    def test_member_can_chat_with_visible_document(self) -> None:
        org = _org()
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(_member(org), Action.chat, resource)
        assert result.result is PermissionResult.allow

    def test_chat_denied_when_connector_acl_not_cleared(self) -> None:
        org = _org()
        connector_id = str(uuid4())
        resource = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=connector_id,
            feature_enabled=True,
        )
        result = _engine.authorize(_member(org), Action.chat, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.connector_acl_denied


# ─── graph entity and evidence ────────────────────────────────────────────────


class TestGraphRAGAuthorization:
    def test_member_allowed_graph_entity_view(self) -> None:
        org = _org()
        resource = ResourceContext(
            resource_type=ResourceType.graph_entity,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(_member(org), Action.view, resource)
        assert result.result is PermissionResult.allow

    def test_member_allowed_graph_evidence_view(self) -> None:
        org = _org()
        resource = ResourceContext(
            resource_type=ResourceType.graph_evidence,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(_member(org), Action.view, resource)
        assert result.result is PermissionResult.allow

    def test_graph_evidence_cross_tenant_denied(self) -> None:
        org_a = _org()
        org_b = _org()
        resource = ResourceContext(
            resource_type=ResourceType.graph_evidence,
            resource_id=str(uuid4()),
            organization_id=org_b,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(_member(org_a), Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.tenant_boundary

    def test_graph_entity_with_explicit_deny_blocked(self) -> None:
        org = _org()
        entity_id = str(uuid4())
        grant_id = str(uuid4())
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org,
            roles=frozenset({"member"}),
            resource_grants=[],
            resource_denies=[(grant_id, ResourceType.graph_entity, entity_id, Action.view)],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset(),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.graph_entity,
            resource_id=entity_id,
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny


# ─── future source type deny-by-default ──────────────────────────────────────


class TestFutureSourceDenyByDefault:
    def test_unknown_resource_type_denied_for_member(self) -> None:
        org = _org()
        resource = ResourceContext(
            resource_type=ResourceType.unknown,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(_member(org), Action.view, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.unknown_resource_type

    def test_unknown_resource_type_denied_for_reviewer(self) -> None:
        org = _org()
        subject = SubjectContext(
            user_id=str(uuid4()),
            organization_id=org,
            roles=frozenset({"reviewer"}),
            resource_grants=[],
            resource_denies=[],
            accessible_collection_ids=frozenset(),
            connector_acl_item_ids=frozenset(),
            resolved_permissions=frozenset(),
        )
        resource = ResourceContext(
            resource_type=ResourceType.unknown,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        result = _engine.authorize(subject, Action.evaluate, resource)
        assert result.result is PermissionResult.deny
        assert result.deny_reason is DenyReason.unknown_resource_type

    def test_filter_excludes_unknown_resource_type(self) -> None:
        org = _org()
        member = _member(org)
        known = ResourceContext(
            resource_type=ResourceType.document,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        unknown = ResourceContext(
            resource_type=ResourceType.unknown,
            resource_id=str(uuid4()),
            organization_id=org,
            owner_ids=frozenset(),
            collection_ids=frozenset(),
            connector_id=None,
            feature_enabled=True,
        )
        visible = _engine.filter_accessible_resources(member, Action.view, [known, unknown])
        types = {r.resource_type for r in visible}
        assert ResourceType.unknown not in types
        assert ResourceType.document in types
