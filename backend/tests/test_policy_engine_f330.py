"""Tests for F330: Backend authorization policy engine.

Covers:
- Unit tests for every precedence rule in the chain
- Role matrix: owner, admin, member, viewer
- Tenant boundary isolation
- Unknown resource type defaults-to-deny
- Decision explanation output
- filter_accessible_resources bulk filtering
- API key subject path
- Explicit deny overrides explicit allow precedence
- Collection-allow and connector ACL paths
- Feature entitlement gate
"""

import os
import re

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

from app.auth.policy_engine import (
    Action,
    AuthorizationResult,
    DenyReason,
    PermissionResult,
    PolicyEngine,
    ResourceContext,
    ResourceType,
    SubjectContext,
)
from app.models.permissions import PermissionType, ROLE_PERMISSIONS


# ── Helpers ───────────────────────────────────────────────────────────────────

ORG_A = "aaaaaaaa-0000-0000-0000-000000000001"
ORG_B = "bbbbbbbb-0000-0000-0000-000000000002"

USER_1 = "00000000-0000-0000-0000-000000000001"
USER_2 = "00000000-0000-0000-0000-000000000002"
USER_3 = "00000000-0000-0000-0000-000000000003"

COL_A = "cccccccc-0000-0000-0000-000000000001"
COL_B = "cccccccc-0000-0000-0000-000000000002"

CONN_A = "dddddddd-0000-0000-0000-000000000001"


def _subject(role: str, org: str = ORG_A, user: str = USER_1) -> SubjectContext:
    perms = ROLE_PERMISSIONS.get(role, frozenset())
    return SubjectContext(
        user_id=user,
        organization_id=org,
        roles=frozenset({role}),
        resolved_permissions=perms,
    )


def _doc_resource(org: str = ORG_A, **kwargs) -> ResourceContext:
    return ResourceContext(resource_type=ResourceType.document, organization_id=org, **kwargs)


engine = PolicyEngine()


def authorize(subject, action, resource) -> AuthorizationResult:
    return engine.authorize(subject, action, resource)


# ── Rule 1: no_organization_context ───────────────────────────────────────────


def test_rule1_no_org_context_denies():
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=None,
        roles=frozenset({"owner"}),
        resolved_permissions=ROLE_PERMISSIONS["owner"],
    )
    result = authorize(subject, Action.view, _doc_resource())
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.no_organization_context
    assert result.matched_rule == "no_organization_context"


def test_rule1_no_org_context_denies_even_owner():
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=None,
        roles=frozenset({"owner"}),
        resolved_permissions=ROLE_PERMISSIONS["owner"],
    )
    result = authorize(subject, Action.delete, _doc_resource())
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.no_organization_context


# ── Rule 2: tenant_boundary ───────────────────────────────────────────────────


def test_rule2_cross_org_denied():
    subject = _subject("owner", org=ORG_A)
    resource = _doc_resource(org=ORG_B)
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.tenant_boundary
    assert result.matched_rule == "tenant_boundary"


def test_rule2_same_org_passes():
    subject = _subject("member", org=ORG_A)
    resource = _doc_resource(org=ORG_A)
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.allow


def test_rule2_none_org_resource_passes_boundary():
    """Resource with org=None is org-neutral; any subject org passes."""
    subject = _subject("member", org=ORG_A)
    resource = ResourceContext(resource_type=ResourceType.document, organization_id=None)
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.allow


def test_rule2_owner_cannot_cross_tenant_boundary():
    subject = _subject("owner", org=ORG_A)
    resource = _doc_resource(org=ORG_B)
    result = authorize(subject, Action.manage, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.tenant_boundary


# ── Rule 3: system_deny ───────────────────────────────────────────────────────


def test_rule3_system_resource_denied_for_all():
    for role in ("owner", "admin", "member", "viewer"):
        subject = _subject(role)
        resource = ResourceContext(
            resource_type=ResourceType.document,
            organization_id=ORG_A,
            is_system_resource=True,
        )
        result = authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny, f"role={role} should be denied"
        assert result.deny_reason is DenyReason.system_deny


def test_rule3_system_deny_blocks_owner():
    subject = _subject("owner")
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        is_system_resource=True,
    )
    result = authorize(subject, Action.manage, resource)
    assert result.matched_rule == "system_deny"


# ── Rule 4: unknown_resource_type (before owner override) ────────────────────


# ── Rule 5: owner_admin_override ──────────────────────────────────────────────


def test_rule4_owner_can_access_any_resource_type():
    subject = _subject("owner")
    for rt in (
        ResourceType.document,
        ResourceType.collection,
        ResourceType.connector,
        ResourceType.evaluation,
        ResourceType.graph_entity,
        ResourceType.api_key,
    ):
        resource = ResourceContext(resource_type=rt, organization_id=ORG_A)
        result = authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.allow, f"owner denied for {rt}"
        assert result.matched_rule == "owner_admin_override"


def test_rule4_admin_override_applies():
    subject = _subject("admin")
    resource = _doc_resource()
    result = authorize(subject, Action.delete, resource)
    assert result.result is PermissionResult.allow
    assert result.matched_rule == "owner_admin_override"


def test_rule4_member_does_not_trigger_override():
    subject = _subject("member")
    resource = _doc_resource()
    result = authorize(subject, Action.delete, resource)
    # member lacks documents:delete
    assert result.result is PermissionResult.deny
    assert result.matched_rule != "owner_admin_override"


# ── Rule 5: explicit_resource_deny ────────────────────────────────────────────


def test_rule5_explicit_deny_blocks_member():
    subject = _subject("member", user=USER_1)
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        explicit_deny_user_ids=[USER_1],
    )
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.explicit_resource_deny
    assert result.matched_rule == "explicit_resource_deny"


def test_rule5_explicit_deny_does_not_affect_other_user():
    subject = _subject("member", user=USER_2)
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        explicit_deny_user_ids=[USER_1],
    )
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.allow


def test_rule5_explicit_deny_takes_precedence_over_explicit_allow():
    """A user in both deny and allow lists must be denied (deny wins via rule order)."""
    subject = _subject("member", user=USER_1)
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        explicit_deny_user_ids=[USER_1],
        explicit_allow_user_ids=[USER_1],
    )
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.explicit_resource_deny


# ── Rule 6: explicit_resource_allow ──────────────────────────────────────────


def test_rule6_explicit_allow_grants_access_regardless_of_role():
    # viewer normally cannot delete, but explicit allow should grant access
    subject = _subject("viewer", user=USER_1)
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        explicit_allow_user_ids=[USER_1],
    )
    result = authorize(subject, Action.delete, resource)
    assert result.result is PermissionResult.allow
    assert result.matched_rule == "explicit_resource_allow"


def test_rule6_explicit_allow_only_for_matching_user():
    subject = _subject("viewer", user=USER_2)
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        explicit_allow_user_ids=[USER_1],
    )
    result = authorize(subject, Action.view, resource)
    # viewer has documents:view so still allowed, but by role_permission not explicit_allow
    assert result.result is PermissionResult.allow
    assert result.matched_rule != "explicit_resource_allow"


# ── Rule 7: collection_allow ─────────────────────────────────────────────────


def test_rule7_collection_allow_grants_document_access():
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=ORG_A,
        roles=frozenset({"member"}),
        resolved_permissions=frozenset({PermissionType.chat_use_collections}),
    )
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        collection_ids=[COL_A],
        subject_accessible_collection_ids=[COL_A],
    )
    result = authorize(subject, Action.chat, resource)
    assert result.result is PermissionResult.allow
    assert result.matched_rule == "collection_allow"


def test_rule7_collection_allow_requires_chat_use_collections_permission():
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=ORG_A,
        roles=frozenset({"member"}),
        resolved_permissions=frozenset(),  # no permissions
    )
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        collection_ids=[COL_A],
        subject_accessible_collection_ids=[COL_A],
    )
    result = authorize(subject, Action.view, resource)
    # No permissions → collection_allow skipped, role_permission fails
    assert result.result is PermissionResult.deny


def test_rule7_collection_allow_skipped_when_no_overlap():
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=ORG_A,
        roles=frozenset({"member"}),
        resolved_permissions=frozenset({PermissionType.chat_use_collections}),
    )
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        collection_ids=[COL_A],
        subject_accessible_collection_ids=[COL_B],  # no overlap
    )
    result = authorize(subject, Action.chat, resource)
    # Falls through to role_permission; member has chat_use not chat_use_collections mapping
    assert "collection_allow" in " ".join(result.trace)


def test_rule7_collection_allow_not_applied_to_connector_type():
    """Connectors are not collection-eligible; rule 7 must be skipped."""
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=ORG_A,
        roles=frozenset({"member"}),
        resolved_permissions=frozenset({PermissionType.chat_use_collections}),
    )
    resource = ResourceContext(
        resource_type=ResourceType.connector,
        organization_id=ORG_A,
        collection_ids=[COL_A],
        subject_accessible_collection_ids=[COL_A],
    )
    result = authorize(subject, Action.view, resource)
    # connector:view requires documents:view; member has it, so allow
    assert result.matched_rule != "collection_allow"


# ── Rule 8: connector_acl ────────────────────────────────────────────────────


def test_rule8_connector_acl_allows_listed_user():
    subject = _subject("viewer", user=USER_1)
    resource = ResourceContext(
        resource_type=ResourceType.connector_source_item,
        organization_id=ORG_A,
        connector_id=CONN_A,
        connector_allowed_user_ids=[USER_1, USER_2],
    )
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.allow
    assert result.matched_rule == "connector_acl"


def test_rule8_connector_acl_denies_unlisted_user():
    subject = _subject("member", user=USER_3)
    resource = ResourceContext(
        resource_type=ResourceType.connector_source_item,
        organization_id=ORG_A,
        connector_id=CONN_A,
        connector_allowed_user_ids=[USER_1, USER_2],
    )
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.connector_acl_denied


def test_rule8_connector_no_acl_falls_through_to_role():
    """Empty connector_allowed_user_ids means no ACL filter; falls through to role check."""
    subject = _subject("member", user=USER_1)
    resource = ResourceContext(
        resource_type=ResourceType.connector_source_item,
        organization_id=ORG_A,
        connector_id=CONN_A,
        connector_allowed_user_ids=[],  # no ACL
    )
    result = authorize(subject, Action.view, resource)
    # member has documents:view
    assert result.result is PermissionResult.allow
    assert result.matched_rule == "role_permission"


def test_rule8_connector_acl_skipped_when_no_connector_id():
    subject = _subject("member", user=USER_1)
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        connector_id=None,
        connector_allowed_user_ids=[USER_2],  # non-empty but connector_id is None
    )
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.allow
    assert result.matched_rule == "role_permission"


# ── Rule 9: role_permission ───────────────────────────────────────────────────


def test_rule9_member_can_view_document():
    result = authorize(_subject("member"), Action.view, _doc_resource())
    assert result.result is PermissionResult.allow
    assert result.matched_rule == "role_permission"


def test_rule9_member_cannot_delete_document():
    result = authorize(_subject("member"), Action.delete, _doc_resource())
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.insufficient_role


def test_rule9_viewer_can_view_document():
    result = authorize(_subject("viewer"), Action.view, _doc_resource())
    assert result.result is PermissionResult.allow


def test_rule9_viewer_cannot_upload_document():
    result = authorize(_subject("viewer"), Action.create, _doc_resource())
    assert result.result is PermissionResult.deny


def test_rule9_viewer_cannot_manage_collection():
    resource = ResourceContext(resource_type=ResourceType.collection, organization_id=ORG_A)
    result = authorize(_subject("viewer"), Action.manage, resource)
    assert result.result is PermissionResult.deny


def test_rule9_developer_can_create_api_key():
    resource = ResourceContext(resource_type=ResourceType.api_key, organization_id=ORG_A)
    result = authorize(_subject("developer"), Action.create, resource)
    assert result.result is PermissionResult.allow


def test_rule9_viewer_cannot_create_api_key():
    resource = ResourceContext(resource_type=ResourceType.api_key, organization_id=ORG_A)
    result = authorize(_subject("viewer"), Action.create, resource)
    assert result.result is PermissionResult.deny


def test_rule9_missing_permission_trace_shows_missing_perms():
    result = authorize(_subject("viewer"), Action.delete, _doc_resource())
    assert any("missing=" in step for step in result.trace)


# ── Rule 10: feature_entitlement ─────────────────────────────────────────────


def test_rule10_feature_disabled_denies_non_admin():
    resource = ResourceContext(
        resource_type=ResourceType.graph_entity,
        organization_id=ORG_A,
        feature_enabled=False,
    )
    # viewer has graph:view but feature gate fires before role_permission
    result = authorize(_subject("viewer"), Action.view, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.feature_not_entitled
    assert result.matched_rule == "feature_entitlement"


def test_rule10_feature_disabled_admin_bypasses_gate():
    """Admin override (rule 5) fires before feature_entitlement (rule 10)."""
    resource = ResourceContext(
        resource_type=ResourceType.graph_entity,
        organization_id=ORG_A,
        feature_enabled=False,
    )
    result = authorize(_subject("admin"), Action.view, resource)
    assert result.result is PermissionResult.allow
    assert result.matched_rule == "owner_admin_override"


def test_rule10_feature_enabled_allows():
    resource = ResourceContext(
        resource_type=ResourceType.graph_entity,
        organization_id=ORG_A,
        feature_enabled=True,
    )
    result = authorize(_subject("viewer"), Action.view, resource)
    assert result.result is PermissionResult.allow


def test_rule10_feature_none_no_gate():
    """feature_enabled=None means no gate; access determined by role."""
    resource = ResourceContext(
        resource_type=ResourceType.graph_entity,
        organization_id=ORG_A,
        feature_enabled=None,
    )
    result = authorize(_subject("viewer"), Action.view, resource)
    assert result.result is PermissionResult.allow


# ── Rule 4 (reordered): unknown_resource_type ────────────────────────────────
# Unknown type check fires before owner_admin_override so that all roles,
# including admin/owner, are denied for unregistered future resource types.


def test_rule_unknown_resource_type_always_denies_all_roles():
    for role in ("owner", "admin", "member", "viewer"):
        subject = _subject(role)
        resource = ResourceContext(resource_type=ResourceType.unknown, organization_id=ORG_A)
        result = authorize(subject, Action.view, resource)
        assert result.result is PermissionResult.deny, f"role={role} should be denied"
        assert result.deny_reason is DenyReason.unknown_resource_type


def test_rule_unknown_resource_type_denies_on_all_actions():
    subject = _subject("member")
    resource = ResourceContext(resource_type=ResourceType.unknown, organization_id=ORG_A)
    for action in Action:
        result = authorize(subject, action, resource)
        assert result.result is PermissionResult.deny


# ── Role matrix ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "role,action,resource_type,expected",
    [
        # owner
        ("owner", Action.view, ResourceType.document, PermissionResult.allow),
        ("owner", Action.delete, ResourceType.document, PermissionResult.allow),
        ("owner", Action.manage, ResourceType.collection, PermissionResult.allow),
        ("owner", Action.sync, ResourceType.connector, PermissionResult.allow),
        ("owner", Action.evaluate, ResourceType.evaluation, PermissionResult.allow),
        ("owner", Action.view, ResourceType.graph_entity, PermissionResult.allow),
        ("owner", Action.delete, ResourceType.api_key, PermissionResult.allow),
        # admin
        ("admin", Action.view, ResourceType.document, PermissionResult.allow),
        ("admin", Action.delete, ResourceType.document, PermissionResult.allow),
        ("admin", Action.manage, ResourceType.collection, PermissionResult.allow),
        ("admin", Action.sync, ResourceType.connector, PermissionResult.allow),
        # member
        ("member", Action.view, ResourceType.document, PermissionResult.allow),
        ("member", Action.create, ResourceType.document, PermissionResult.allow),
        ("member", Action.delete, ResourceType.document, PermissionResult.deny),
        ("member", Action.manage, ResourceType.document, PermissionResult.deny),
        ("member", Action.view, ResourceType.collection, PermissionResult.allow),
        ("member", Action.manage, ResourceType.collection, PermissionResult.deny),
        ("member", Action.delete, ResourceType.api_key, PermissionResult.deny),
        # viewer
        ("viewer", Action.view, ResourceType.document, PermissionResult.allow),
        ("viewer", Action.create, ResourceType.document, PermissionResult.deny),
        ("viewer", Action.delete, ResourceType.document, PermissionResult.deny),
        ("viewer", Action.view, ResourceType.collection, PermissionResult.allow),
        ("viewer", Action.manage, ResourceType.collection, PermissionResult.deny),
        ("viewer", Action.delete, ResourceType.collection, PermissionResult.deny),
        ("viewer", Action.view, ResourceType.evaluation, PermissionResult.allow),
        ("viewer", Action.evaluate, ResourceType.evaluation, PermissionResult.deny),
        ("viewer", Action.view, ResourceType.graph_entity, PermissionResult.allow),
        ("viewer", Action.manage, ResourceType.graph_entity, PermissionResult.deny),
    ],
)
def test_role_matrix(role, action, resource_type, expected):
    subject = _subject(role)
    resource = ResourceContext(resource_type=resource_type, organization_id=ORG_A)
    result = authorize(subject, action, resource)
    assert result.result is expected, (
        f"role={role} action={action} resource={resource_type}: "
        f"expected {expected}, got {result.result} "
        f"(rule={result.matched_rule}, reason={result.deny_reason})"
    )


# ── Tenant boundary isolation ─────────────────────────────────────────────────


def test_tenant_boundary_owner_cannot_see_other_org_document():
    subject = _subject("owner", org=ORG_A)
    resource = _doc_resource(org=ORG_B)
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.tenant_boundary


def test_tenant_boundary_admin_cannot_manage_other_org_collection():
    subject = _subject("admin", org=ORG_A)
    resource = ResourceContext(resource_type=ResourceType.collection, organization_id=ORG_B)
    result = authorize(subject, Action.manage, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.tenant_boundary


def test_tenant_boundary_member_same_org_passes():
    subject = _subject("member", org=ORG_A)
    resource = _doc_resource(org=ORG_A)
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.allow


def test_tenant_boundary_cross_org_explicit_allow_still_denied():
    """Explicit allow for a user cannot override the tenant boundary."""
    subject = _subject("member", org=ORG_A, user=USER_1)
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_B,
        explicit_allow_user_ids=[USER_1],
    )
    result = authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.tenant_boundary


# ── filter_accessible_resources ──────────────────────────────────────────────


def test_filter_returns_only_accessible_resources():
    subject = _subject("member")
    resources = [
        ResourceContext(resource_type=ResourceType.document, organization_id=ORG_A),
        ResourceContext(resource_type=ResourceType.document, organization_id=ORG_B),  # cross-org
        ResourceContext(resource_type=ResourceType.document, organization_id=ORG_A),
    ]
    accessible = engine.filter_accessible_resources(subject, Action.view, resources)
    assert len(accessible) == 2
    assert all(r.organization_id == ORG_A for r in accessible)


def test_filter_empty_list_returns_empty():
    subject = _subject("owner")
    result = engine.filter_accessible_resources(subject, Action.delete, [])
    assert result == []


def test_filter_owner_gets_all_same_org_resources():
    subject = _subject("owner")
    resources = [
        ResourceContext(resource_type=rt, organization_id=ORG_A)
        for rt in (ResourceType.document, ResourceType.collection, ResourceType.evaluation)
    ]
    accessible = engine.filter_accessible_resources(subject, Action.view, resources)
    assert len(accessible) == 3


def test_filter_excludes_system_resources():
    subject = _subject("owner")
    resources = [
        ResourceContext(resource_type=ResourceType.document, organization_id=ORG_A),
        ResourceContext(
            resource_type=ResourceType.document,
            organization_id=ORG_A,
            is_system_resource=True,
        ),
    ]
    accessible = engine.filter_accessible_resources(subject, Action.view, resources)
    assert len(accessible) == 1
    assert not accessible[0].is_system_resource


# ── API key subject ───────────────────────────────────────────────────────────


def test_api_key_subject_with_sufficient_permissions():
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=ORG_A,
        roles=frozenset(),
        resolved_permissions=frozenset({PermissionType.documents_view}),
        is_api_key=True,
    )
    result = authorize(subject, Action.view, _doc_resource())
    assert result.result is PermissionResult.allow


def test_api_key_subject_denied_without_permission():
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=ORG_A,
        roles=frozenset(),
        resolved_permissions=frozenset(),
        is_api_key=True,
    )
    result = authorize(subject, Action.view, _doc_resource())
    assert result.result is PermissionResult.deny


def test_api_key_cannot_cross_tenant_boundary():
    subject = SubjectContext(
        user_id=USER_1,
        organization_id=ORG_A,
        roles=frozenset(),
        resolved_permissions=frozenset({PermissionType.documents_view}),
        is_api_key=True,
    )
    result = authorize(subject, Action.view, _doc_resource(org=ORG_B))
    assert result.result is PermissionResult.deny
    assert result.deny_reason is DenyReason.tenant_boundary


# ── explain_decision ──────────────────────────────────────────────────────────


def test_explain_decision_allow():
    subject = _subject("member")
    resource = _doc_resource()
    result = authorize(subject, Action.view, resource)
    explanation = engine.explain_decision(result)

    assert "ALLOW" in explanation
    assert subject.user_id in explanation
    assert ORG_A in explanation
    assert "view" in explanation
    assert "document" in explanation
    assert result.matched_rule in explanation
    assert result.request_id in explanation
    assert "→" in explanation


def test_explain_decision_deny_with_reason():
    subject = _subject("viewer")
    resource = _doc_resource()
    result = authorize(subject, Action.delete, resource)
    explanation = engine.explain_decision(result)

    assert "DENY" in explanation
    assert "insufficient_role" in explanation
    assert result.deny_reason.value in explanation


def test_explain_decision_includes_trace():
    subject = _subject("member")
    resource = _doc_resource()
    result = authorize(subject, Action.view, resource)
    explanation = engine.explain_decision(result)
    # Trace lines appear as "→ rule_name:..."
    assert re.search(r"→\s+\w+", explanation)


def test_explain_decision_resource_id_in_output():
    subject = _subject("member")
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        resource_id="some-doc-id",
    )
    result = authorize(subject, Action.view, resource)
    explanation = engine.explain_decision(result)
    assert "some-doc-id" in explanation


# ── Audit metadata ────────────────────────────────────────────────────────────


def test_result_contains_request_id():
    result = authorize(_subject("member"), Action.view, _doc_resource())
    assert result.request_id  # non-empty string


def test_result_request_id_is_consistent_when_passed():
    fixed_rid = "test-request-123"
    result = engine.authorize(
        _subject("member"), Action.view, _doc_resource(), request_id=fixed_rid
    )
    assert result.request_id == fixed_rid


def test_result_contains_all_metadata_fields():
    subject = _subject("member")
    resource = ResourceContext(
        resource_type=ResourceType.document,
        organization_id=ORG_A,
        resource_id="doc-abc",
    )
    result = authorize(subject, Action.view, resource)
    assert result.subject_id == USER_1
    assert result.organization_id == ORG_A
    assert result.resource_type is ResourceType.document
    assert result.resource_id == "doc-abc"
    assert result.action is Action.view
    assert isinstance(result.trace, list)
    assert len(result.trace) > 0


# ── Citation and graph evidence paths ────────────────────────────────────────


def test_citation_view_requires_chat_use():
    resource = ResourceContext(resource_type=ResourceType.citation, organization_id=ORG_A)
    # viewer has chat:use
    assert authorize(_subject("viewer"), Action.view, resource).result is PermissionResult.allow
    # reviewer has chat:use too
    assert authorize(_subject("reviewer"), Action.cite, resource).result is PermissionResult.allow


def test_graph_evidence_requires_graph_view():
    resource = ResourceContext(resource_type=ResourceType.graph_evidence, organization_id=ORG_A)
    assert authorize(_subject("viewer"), Action.view, resource).result is PermissionResult.allow
    assert authorize(_subject("viewer"), Action.manage, resource).result is PermissionResult.deny


# ── Saved answer and knowledge card ──────────────────────────────────────────


def test_saved_answer_manage_requires_chat_manage_sessions():
    resource = ResourceContext(resource_type=ResourceType.saved_answer, organization_id=ORG_A)
    # member has chat:manage_sessions
    assert authorize(_subject("member"), Action.manage, resource).result is PermissionResult.allow
    # viewer does not
    assert authorize(_subject("viewer"), Action.manage, resource).result is PermissionResult.deny


def test_knowledge_card_manage_requires_documents_manage():
    resource = ResourceContext(resource_type=ResourceType.knowledge_card, organization_id=ORG_A)
    assert authorize(_subject("viewer"), Action.manage, resource).result is PermissionResult.deny
    assert authorize(_subject("admin"), Action.manage, resource).result is PermissionResult.allow
