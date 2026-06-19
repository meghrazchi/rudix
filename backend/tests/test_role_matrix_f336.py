"""F336: Role/resource/action authorization matrix regression tests.

pytest.mark.authorization_regression — full parametrized matrix covering
the 8 built-in roles × key ResourceTypes × Actions against the PolicyEngine's
11-rule precedence chain.

Expected allow/deny per combination reflects the ROLE_PERMISSIONS map
and the owner_admin_override rule.
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
    PermissionResult,
    PolicyEngine,
    ResourceContext,
    ResourceType,
    SubjectContext,
)

pytestmark = pytest.mark.authorization_regression

_engine = PolicyEngine()

# ─── helpers ─────────────────────────────────────────────────────────────────


def _org() -> str:
    return str(uuid4())


def _sub(org_id: str, role: str, permissions: frozenset[str] = frozenset()) -> SubjectContext:
    return SubjectContext(
        user_id=str(uuid4()),
        organization_id=org_id,
        roles=frozenset({role}),
        resource_grants=[],
        resource_denies=[],
        accessible_collection_ids=frozenset(),
        connector_acl_item_ids=frozenset(),
        resolved_permissions=permissions,
    )


def _res(
    org_id: str,
    rtype: ResourceType = ResourceType.document,
    feature_enabled: bool = True,
) -> ResourceContext:
    return ResourceContext(
        resource_type=rtype,
        resource_id=str(uuid4()),
        organization_id=org_id,
        owner_ids=frozenset(),
        collection_ids=frozenset(),
        connector_id=None,
        feature_enabled=feature_enabled,
    )


def _allow(role: str, rtype: ResourceType, action: Action) -> None:
    org = _org()
    result = _engine.authorize(_sub(org, role), action, _res(org, rtype))
    assert result.result is PermissionResult.allow, (
        f"Expected ALLOW for role={role} resource={rtype.value} action={action.value}, "
        f"got DENY (reason={result.deny_reason}, rule={result.matched_rule})"
    )


def _deny(role: str, rtype: ResourceType, action: Action) -> None:
    org = _org()
    result = _engine.authorize(_sub(org, role), action, _res(org, rtype))
    assert result.result is PermissionResult.deny, (
        f"Expected DENY for role={role} resource={rtype.value} action={action.value}, "
        f"got ALLOW (rule={result.matched_rule})"
    )


# ─── owner / admin override ───────────────────────────────────────────────────

OWNER_ADMIN_COMBINATIONS = [
    (role, rtype, action)
    for role in ("owner", "admin")
    for rtype in (
        ResourceType.document,
        ResourceType.collection,
        ResourceType.connector,
        ResourceType.evaluation,
        ResourceType.graph_entity,
        ResourceType.saved_answer,
    )
    for action in (Action.view, Action.create, Action.delete, Action.manage)
]


@pytest.mark.parametrize("role,rtype,action", OWNER_ADMIN_COMBINATIONS)
def test_owner_admin_always_allowed(role: str, rtype: ResourceType, action: Action) -> None:
    _allow(role, rtype, action)


# ─── member matrix ────────────────────────────────────────────────────────────

MEMBER_ALLOW = [
    (ResourceType.document, Action.view),
    (ResourceType.document, Action.search),
    (ResourceType.collection, Action.list),
    (ResourceType.collection, Action.view),
    (ResourceType.connector, Action.list),
    (ResourceType.graph_entity, Action.view),
    (ResourceType.saved_answer, Action.view),
]

MEMBER_DENY = [
    (ResourceType.document, Action.delete),
    (ResourceType.document, Action.manage),
    (ResourceType.collection, Action.delete),
    (ResourceType.collection, Action.manage),
    (ResourceType.connector, Action.manage),
    (ResourceType.connector, Action.delete),
    (ResourceType.evaluation, Action.manage),
]


@pytest.mark.parametrize("rtype,action", MEMBER_ALLOW)
def test_member_allowed(rtype: ResourceType, action: Action) -> None:
    _allow("member", rtype, action)


@pytest.mark.parametrize("rtype,action", MEMBER_DENY)
def test_member_denied(rtype: ResourceType, action: Action) -> None:
    _deny("member", rtype, action)


# ─── viewer matrix ────────────────────────────────────────────────────────────

VIEWER_ALLOW = [
    (ResourceType.document, Action.view),
    (ResourceType.collection, Action.view),
    (ResourceType.graph_entity, Action.view),
]

VIEWER_DENY = [
    (ResourceType.document, Action.create),
    (ResourceType.document, Action.delete),
    (ResourceType.document, Action.manage),
    (ResourceType.collection, Action.create),
    (ResourceType.collection, Action.delete),
    (ResourceType.connector, Action.manage),
    (ResourceType.evaluation, Action.create),
]


@pytest.mark.parametrize("rtype,action", VIEWER_ALLOW)
def test_viewer_allowed(rtype: ResourceType, action: Action) -> None:
    _allow("viewer", rtype, action)


@pytest.mark.parametrize("rtype,action", VIEWER_DENY)
def test_viewer_denied(rtype: ResourceType, action: Action) -> None:
    _deny("viewer", rtype, action)


# ─── reviewer matrix ─────────────────────────────────────────────────────────

REVIEWER_ALLOW = [
    (ResourceType.document, Action.view),
    (ResourceType.evaluation, Action.view),
    (ResourceType.evaluation, Action.evaluate),
]

REVIEWER_DENY = [
    (ResourceType.document, Action.delete),
    (ResourceType.connector, Action.manage),
    (ResourceType.evaluation, Action.manage),
]


@pytest.mark.parametrize("rtype,action", REVIEWER_ALLOW)
def test_reviewer_allowed(rtype: ResourceType, action: Action) -> None:
    _allow("reviewer", rtype, action)


@pytest.mark.parametrize("rtype,action", REVIEWER_DENY)
def test_reviewer_denied(rtype: ResourceType, action: Action) -> None:
    _deny("reviewer", rtype, action)


# ─── billing_admin matrix ─────────────────────────────────────────────────────


def test_billing_admin_denied_document_view() -> None:
    _deny("billing_admin", ResourceType.document, Action.view)


def test_billing_admin_denied_collection_manage() -> None:
    _deny("billing_admin", ResourceType.collection, Action.manage)


def test_billing_admin_denied_connector_manage() -> None:
    _deny("billing_admin", ResourceType.connector, Action.manage)


# ─── developer matrix ─────────────────────────────────────────────────────────


def test_developer_allowed_document_view() -> None:
    _allow("developer", ResourceType.document, Action.view)


def test_developer_denied_connector_delete() -> None:
    _deny("developer", ResourceType.connector, Action.delete)


def test_developer_denied_evaluation_manage() -> None:
    _deny("developer", ResourceType.evaluation, Action.manage)


# ─── security_admin matrix ───────────────────────────────────────────────────


def test_security_admin_denied_document_view() -> None:
    _deny("security_admin", ResourceType.document, Action.view)


def test_security_admin_denied_collection_manage() -> None:
    _deny("security_admin", ResourceType.collection, Action.manage)


# ─── future / unknown resource always deny for all non-owner roles ────────────

NON_ADMIN_ROLES = ("member", "viewer", "reviewer", "billing_admin", "developer", "security_admin")


@pytest.mark.parametrize("role", NON_ADMIN_ROLES)
def test_unknown_resource_denied_for_non_admin(role: str) -> None:
    org = _org()
    result = _engine.authorize(_sub(org, role), Action.view, _res(org, ResourceType.unknown))
    assert result.result is PermissionResult.deny


def test_unknown_resource_denied_for_owner() -> None:
    org = _org()
    result = _engine.authorize(_sub(org, "owner"), Action.view, _res(org, ResourceType.unknown))
    assert result.result is PermissionResult.deny


# ─── feature entitlement gate ────────────────────────────────────────────────


def test_feature_disabled_blocks_member() -> None:
    org = _org()
    resource = _res(org, ResourceType.document, feature_enabled=False)
    result = _engine.authorize(_sub(org, "member"), Action.view, resource)
    assert result.result is PermissionResult.deny


def test_feature_disabled_admin_still_allowed() -> None:
    org = _org()
    resource = _res(org, ResourceType.document, feature_enabled=False)
    result = _engine.authorize(_sub(org, "admin"), Action.view, resource)
    assert result.result is PermissionResult.allow


# ─── explicit deny overrides role allow ──────────────────────────────────────


def test_explicit_deny_overrides_member_allow() -> None:
    org = _org()
    doc_id = str(uuid4())
    grant_id = str(uuid4())
    subject = SubjectContext(
        user_id=str(uuid4()),
        organization_id=org,
        roles=frozenset({"member"}),
        resource_grants=[],
        resource_denies=[(grant_id, ResourceType.document, doc_id, Action.view)],
        accessible_collection_ids=frozenset(),
        connector_acl_item_ids=frozenset(),
        resolved_permissions=frozenset(),
    )
    resource = ResourceContext(
        resource_type=ResourceType.document,
        resource_id=doc_id,
        organization_id=org,
        owner_ids=frozenset(),
        collection_ids=frozenset(),
        connector_id=None,
        feature_enabled=True,
    )
    result = _engine.authorize(subject, Action.view, resource)
    assert result.result is PermissionResult.deny


# ─── trace completeness ───────────────────────────────────────────────────────


def test_trace_is_non_empty_on_allow() -> None:
    org = _org()
    result = _engine.authorize(_sub(org, "member"), Action.view, _res(org, ResourceType.document))
    assert len(result.trace) > 0


def test_trace_is_non_empty_on_deny() -> None:
    org = _org()
    result = _engine.authorize(_sub(org, "member"), Action.delete, _res(org, ResourceType.document))
    assert len(result.trace) > 0


def test_request_id_propagated() -> None:
    org = _org()
    req_id = str(uuid4())
    result = _engine.authorize(
        _sub(org, "member"), Action.view, _res(org, ResourceType.document), request_id=req_id
    )
    assert result.request_id == req_id


# ─── api_key subject ─────────────────────────────────────────────────────────


def test_api_key_subject_with_permission_allowed() -> None:
    org = _org()
    sub = SubjectContext(
        user_id=str(uuid4()),
        organization_id=org,
        roles=frozenset(),
        resource_grants=[],
        resource_denies=[],
        accessible_collection_ids=frozenset(),
        connector_acl_item_ids=frozenset(),
        resolved_permissions=frozenset({"documents:view"}),
    )
    result = _engine.authorize(sub, Action.view, _res(org, ResourceType.document))
    assert result.result is PermissionResult.allow


def test_api_key_subject_without_permission_denied() -> None:
    org = _org()
    sub = SubjectContext(
        user_id=str(uuid4()),
        organization_id=org,
        roles=frozenset(),
        resource_grants=[],
        resource_denies=[],
        accessible_collection_ids=frozenset(),
        connector_acl_item_ids=frozenset(),
        resolved_permissions=frozenset({"documents:upload"}),
    )
    result = _engine.authorize(sub, Action.view, _res(org, ResourceType.document))
    assert result.result is PermissionResult.deny
