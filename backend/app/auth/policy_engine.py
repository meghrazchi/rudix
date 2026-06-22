"""Central authorization policy engine — F330.

Implements a deterministic precedence chain:
  1.  no_organization_context  — subject has no org; deny immediately
  2.  tenant_boundary          — resource belongs to a different org; deny
  3.  system_deny              — resource is a system-internal resource; deny (all roles)
  4.  unknown_resource_type    — ResourceType.unknown; deny (all roles, safety guard)
  5.  owner_admin_override     — subject holds owner or admin role; allow
  6.  explicit_resource_deny   — subject appears in the resource's deny list; deny
  7.  explicit_resource_allow  — subject appears in the resource's allow list; allow
  8.  collection_allow         — resource lives in a collection the subject can access; allow
  9.  connector_acl            — resource is connector-backed; apply connector ACL
 10.  feature_entitlement      — caller pre-resolves feature flag; deny when disabled
 11.  role_permission          — required PermissionType resolved against subject permissions

The engine is stateless and never performs DB lookups. Callers must pre-resolve
permissions, ACL membership, and feature flags into SubjectContext / ResourceContext
before calling authorize().
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.models.permissions import ROLE_PERMISSIONS, PermissionType

# ── Enumerations ─────────────────────────────────────────────────────────────


class ResourceType(StrEnum):
    document = "document"
    collection = "collection"
    connector = "connector"
    connector_source_item = "connector_source_item"
    citation = "citation"
    graph_entity = "graph_entity"
    graph_evidence = "graph_evidence"
    evaluation = "evaluation"
    saved_answer = "saved_answer"
    knowledge_card = "knowledge_card"
    api_key = "api_key"
    # Sentinel for unrecognised future types — always results in deny.
    unknown = "unknown"


class Action(StrEnum):
    list = "list"
    view = "view"
    search = "search"
    chat = "chat"
    cite = "cite"
    create = "create"
    manage = "manage"
    sync = "sync"
    export = "export"
    evaluate = "evaluate"
    delete = "delete"


class PermissionResult(StrEnum):
    allow = "allow"
    deny = "deny"


class DenyReason(StrEnum):
    no_organization_context = "no_organization_context"
    tenant_boundary = "tenant_boundary"
    system_deny = "system_deny"
    explicit_resource_deny = "explicit_resource_deny"
    collection_not_accessible = "collection_not_accessible"
    connector_acl_denied = "connector_acl_denied"
    insufficient_role = "insufficient_role"
    feature_not_entitled = "feature_not_entitled"
    unknown_resource_type = "unknown_resource_type"


# ── Subject ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True, init=False)
class SubjectContext:
    """Resolved subject context passed to the policy engine."""

    user_id: str
    organization_id: str | None
    # Active role names for this session (e.g. ["member"]).
    roles: frozenset[str]
    # Fully resolved permission set (base role + custom role additions).
    resolved_permissions: frozenset[str]
    # True when authenticated via a scoped API key (permissions pre-resolved).
    is_api_key: bool = False
    # Legacy aliases kept for backwards-compatible test and adapter construction.
    resource_grants: tuple[object, ...] = ()
    resource_denies: tuple[object, ...] = ()
    accessible_collection_ids: frozenset[str] = frozenset()
    connector_acl_item_ids: frozenset[str] = frozenset()

    def __init__(
        self,
        *,
        user_id: str,
        organization_id: str | None,
        roles: frozenset[str],
        resolved_permissions: frozenset[str],
        is_api_key: bool = False,
        resource_grants: Sequence[object] | None = None,
        resource_denies: Sequence[object] | None = None,
        accessible_collection_ids: Sequence[str] | None = None,
        connector_acl_item_ids: Sequence[str] | None = None,
    ) -> None:
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "organization_id", organization_id)
        object.__setattr__(self, "roles", frozenset(roles))
        object.__setattr__(self, "resolved_permissions", frozenset(resolved_permissions))
        object.__setattr__(self, "is_api_key", is_api_key)
        object.__setattr__(
            self,
            "resource_grants",
            tuple(resource_grants or ()),
        )
        object.__setattr__(
            self,
            "resource_denies",
            tuple(resource_denies or ()),
        )
        object.__setattr__(
            self,
            "accessible_collection_ids",
            frozenset(accessible_collection_ids or ()),
        )
        object.__setattr__(
            self,
            "connector_acl_item_ids",
            frozenset(connector_acl_item_ids or ()),
        )


# ── Resource ──────────────────────────────────────────────────────────────────


@dataclass(init=False)
class ResourceContext:
    """Describes the resource being accessed, plus its access-control metadata.

    All list/set fields default to empty so callers only set what is known.
    """

    resource_type: ResourceType
    resource_id: str | None = None
    # Owning organisation of the resource. None means org-neutral.
    organization_id: str | None = None
    # User ID that owns the resource (e.g. the creator of an API key).
    owner_user_id: str | None = None
    # Collections this resource belongs to.
    collection_ids: list[str] = field(default_factory=list)
    # Connector that backs this resource (connector_source_item / connector-backed document).
    connector_id: str | None = None
    # User IDs explicitly blocked from this resource regardless of role.
    explicit_deny_user_ids: list[str] = field(default_factory=list)
    # User IDs explicitly granted access to this resource regardless of role.
    explicit_allow_user_ids: list[str] = field(default_factory=list)
    # User IDs granted access via connector ACL (empty means no ACL filter).
    connector_allowed_user_ids: list[str] = field(default_factory=list)
    # Collection IDs the *subject* already has access to (caller pre-resolves).
    subject_accessible_collection_ids: list[str] = field(default_factory=list)
    # System-internal resources (e.g. chain-of-thought, provider secrets) — always deny.
    is_system_resource: bool = False
    # Feature flag gate. None = no gate. False = feature disabled for this org.
    feature_enabled: bool | None = None
    # Legacy aliases kept for backwards-compatible test and adapter construction.
    owner_ids: frozenset[str] = frozenset()
    explicit_denies: list[object] = field(default_factory=list)

    def __init__(
        self,
        *,
        resource_type: ResourceType,
        resource_id: str | None = None,
        organization_id: str | None = None,
        owner_user_id: str | None = None,
        collection_ids: Sequence[str] | None = None,
        connector_id: str | None = None,
        explicit_deny_user_ids: Sequence[str] | None = None,
        explicit_allow_user_ids: Sequence[str] | None = None,
        connector_allowed_user_ids: Sequence[str] | None = None,
        subject_accessible_collection_ids: Sequence[str] | None = None,
        is_system_resource: bool = False,
        feature_enabled: bool | None = None,
        owner_ids: Sequence[str] | None = None,
        explicit_denies: Sequence[object] | None = None,
    ) -> None:
        object.__setattr__(self, "resource_type", resource_type)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "organization_id", organization_id)
        resolved_owner = owner_user_id
        owners = frozenset(owner_ids or ())
        if resolved_owner is None and owners:
            resolved_owner = next(iter(owners))
        object.__setattr__(self, "owner_user_id", resolved_owner)
        object.__setattr__(self, "collection_ids", list(collection_ids or ()))
        object.__setattr__(self, "connector_id", connector_id)
        object.__setattr__(self, "explicit_deny_user_ids", list(explicit_deny_user_ids or ()))
        object.__setattr__(self, "explicit_allow_user_ids", list(explicit_allow_user_ids or ()))
        object.__setattr__(
            self,
            "connector_allowed_user_ids",
            list(connector_allowed_user_ids or ()),
        )
        object.__setattr__(
            self,
            "subject_accessible_collection_ids",
            list(subject_accessible_collection_ids or ()),
        )
        object.__setattr__(self, "is_system_resource", is_system_resource)
        object.__setattr__(self, "feature_enabled", feature_enabled)
        object.__setattr__(self, "owner_ids", owners)
        object.__setattr__(self, "explicit_denies", list(explicit_denies or ()))


# ── Result ────────────────────────────────────────────────────────────────────


@dataclass
class AuthorizationResult:
    """Outcome of a single policy evaluation."""

    result: PermissionResult
    deny_reason: DenyReason | None
    # Name of the rule that terminated evaluation.
    matched_rule: str
    # Ordered list of rule evaluations for explain_decision().
    trace: list[str]
    request_id: str
    subject_id: str
    organization_id: str | None
    resource_type: ResourceType
    resource_id: str | None
    action: Action


# ── Permission mapping ────────────────────────────────────────────────────────

# Maps (ResourceType, Action) → required permissions (ALL must be held).
_RESOURCE_ACTION_PERMISSIONS: dict[tuple[ResourceType, Action], frozenset[str]] = {
    # Document
    (ResourceType.document, Action.list): frozenset({PermissionType.documents_view}),
    (ResourceType.document, Action.view): frozenset({PermissionType.documents_view}),
    (ResourceType.document, Action.search): frozenset({PermissionType.documents_view}),
    (ResourceType.document, Action.chat): frozenset({PermissionType.chat_use}),
    (ResourceType.document, Action.cite): frozenset({PermissionType.chat_use}),
    (ResourceType.document, Action.create): frozenset({PermissionType.documents_upload}),
    (ResourceType.document, Action.manage): frozenset({PermissionType.documents_manage}),
    (ResourceType.document, Action.delete): frozenset({PermissionType.documents_delete}),
    (ResourceType.document, Action.export): frozenset({PermissionType.documents_view}),
    (ResourceType.document, Action.evaluate): frozenset({PermissionType.evaluations_run}),
    # Collection
    (ResourceType.collection, Action.list): frozenset({PermissionType.collections_view}),
    (ResourceType.collection, Action.view): frozenset({PermissionType.collections_view}),
    (ResourceType.collection, Action.search): frozenset({PermissionType.collections_view}),
    (ResourceType.collection, Action.chat): frozenset({PermissionType.chat_use_collections}),
    (ResourceType.collection, Action.create): frozenset({PermissionType.collections_create}),
    (ResourceType.collection, Action.manage): frozenset({PermissionType.collections_manage}),
    (ResourceType.collection, Action.delete): frozenset({PermissionType.collections_delete}),
    (ResourceType.collection, Action.export): frozenset({PermissionType.collections_view}),
    # Connector
    (ResourceType.connector, Action.list): frozenset({PermissionType.documents_view}),
    (ResourceType.connector, Action.view): frozenset({PermissionType.documents_view}),
    (ResourceType.connector, Action.manage): frozenset({PermissionType.documents_manage}),
    (ResourceType.connector, Action.sync): frozenset({PermissionType.documents_manage}),
    (ResourceType.connector, Action.delete): frozenset({PermissionType.documents_manage}),
    # Connector source item
    (ResourceType.connector_source_item, Action.view): frozenset({PermissionType.documents_view}),
    (ResourceType.connector_source_item, Action.search): frozenset({PermissionType.documents_view}),
    # Citation
    (ResourceType.citation, Action.view): frozenset({PermissionType.chat_use}),
    (ResourceType.citation, Action.cite): frozenset({PermissionType.chat_use}),
    (ResourceType.citation, Action.export): frozenset({PermissionType.chat_use}),
    # Graph entity
    (ResourceType.graph_entity, Action.view): frozenset({PermissionType.graph_view}),
    (ResourceType.graph_entity, Action.list): frozenset({PermissionType.graph_view}),
    (ResourceType.graph_entity, Action.search): frozenset({PermissionType.graph_view}),
    (ResourceType.graph_entity, Action.manage): frozenset({PermissionType.graph_entities_manage}),
    (ResourceType.graph_entity, Action.delete): frozenset({PermissionType.graph_entities_manage}),
    # Graph evidence
    (ResourceType.graph_evidence, Action.view): frozenset({PermissionType.graph_view}),
    (ResourceType.graph_evidence, Action.cite): frozenset({PermissionType.graph_view}),
    (ResourceType.graph_evidence, Action.manage): frozenset(
        {PermissionType.graph_relations_manage}
    ),
    # Evaluation
    (ResourceType.evaluation, Action.view): frozenset({PermissionType.evaluations_view}),
    (ResourceType.evaluation, Action.list): frozenset({PermissionType.evaluations_view}),
    (ResourceType.evaluation, Action.create): frozenset({PermissionType.evaluations_create}),
    (ResourceType.evaluation, Action.evaluate): frozenset({PermissionType.evaluations_run}),
    (ResourceType.evaluation, Action.manage): frozenset({PermissionType.evaluations_manage}),
    (ResourceType.evaluation, Action.export): frozenset({PermissionType.evaluations_view}),
    (ResourceType.evaluation, Action.delete): frozenset({PermissionType.evaluations_manage}),
    # Saved answer
    (ResourceType.saved_answer, Action.view): frozenset({PermissionType.chat_use}),
    (ResourceType.saved_answer, Action.list): frozenset({PermissionType.chat_use}),
    (ResourceType.saved_answer, Action.manage): frozenset({PermissionType.chat_manage_sessions}),
    (ResourceType.saved_answer, Action.delete): frozenset({PermissionType.chat_manage_sessions}),
    (ResourceType.saved_answer, Action.export): frozenset({PermissionType.chat_manage_sessions}),
    # Knowledge card
    (ResourceType.knowledge_card, Action.view): frozenset({PermissionType.documents_view}),
    (ResourceType.knowledge_card, Action.list): frozenset({PermissionType.documents_view}),
    (ResourceType.knowledge_card, Action.manage): frozenset({PermissionType.documents_manage}),
    (ResourceType.knowledge_card, Action.delete): frozenset({PermissionType.documents_manage}),
    # API key
    (ResourceType.api_key, Action.list): frozenset({PermissionType.api_keys_list}),
    (ResourceType.api_key, Action.view): frozenset({PermissionType.api_keys_list}),
    (ResourceType.api_key, Action.create): frozenset({PermissionType.api_keys_create}),
    (ResourceType.api_key, Action.manage): frozenset({PermissionType.api_keys_create}),
    (ResourceType.api_key, Action.delete): frozenset({PermissionType.api_keys_revoke}),
}

# Resource types where collection-based allow is evaluated.
_COLLECTION_ELIGIBLE_TYPES: frozenset[ResourceType] = frozenset(
    {
        ResourceType.document,
        ResourceType.connector_source_item,
        ResourceType.citation,
        ResourceType.graph_evidence,
    }
)

_ADMIN_ROLES: frozenset[str] = frozenset({"owner", "admin"})


# ── Engine ────────────────────────────────────────────────────────────────────


class PolicyEngine:
    """Stateless, deterministic authorization policy engine.

    Thread-safe. A single instance can be shared across the entire process.
    """

    def authorize(
        self,
        subject: SubjectContext,
        action: Action,
        resource: ResourceContext,
        *,
        request_id: str | None = None,
    ) -> AuthorizationResult:
        """Evaluate the full precedence chain and return an AuthorizationResult."""
        rid = request_id or str(uuid.uuid4())
        trace: list[str] = []

        def _deny(reason: DenyReason, rule: str) -> AuthorizationResult:
            trace.append(f"{rule}:deny({reason})")
            return AuthorizationResult(
                result=PermissionResult.deny,
                deny_reason=reason,
                matched_rule=rule,
                trace=list(trace),
                request_id=rid,
                subject_id=subject.user_id,
                organization_id=subject.organization_id,
                resource_type=resource.resource_type,
                resource_id=resource.resource_id,
                action=action,
            )

        def _allow(rule: str) -> AuthorizationResult:
            trace.append(f"{rule}:allow")
            return AuthorizationResult(
                result=PermissionResult.allow,
                deny_reason=None,
                matched_rule=rule,
                trace=list(trace),
                request_id=rid,
                subject_id=subject.user_id,
                organization_id=subject.organization_id,
                resource_type=resource.resource_type,
                resource_id=resource.resource_id,
                action=action,
            )

        def _legacy_rule_matches(entries: Sequence[object], resource_type: ResourceType) -> bool:
            for entry in entries:
                if isinstance(entry, tuple) and len(entry) >= 4:
                    _, entry_type, entry_resource_id, entry_action = entry[:4]
                    if (
                        entry_type is resource_type
                        and entry_resource_id == resource.resource_id
                        and entry_action is action
                    ):
                        return True
            return False

        # ── Rule 1: Organization context required ────────────────────────────
        rule = "no_organization_context"
        if subject.organization_id is None:
            return _deny(DenyReason.no_organization_context, rule)
        trace.append(f"{rule}:pass")

        # ── Rule 2: Tenant boundary ──────────────────────────────────────────
        rule = "tenant_boundary"
        if (
            resource.organization_id is not None
            and resource.organization_id != subject.organization_id
        ):
            return _deny(DenyReason.tenant_boundary, rule)
        trace.append(f"{rule}:pass")

        # ── Rule 3: System deny ──────────────────────────────────────────────
        rule = "system_deny"
        if resource.is_system_resource:
            return _deny(DenyReason.system_deny, rule)
        trace.append(f"{rule}:pass")

        # ── Rule 4: Unknown resource type → deny (all roles) ────────────────
        # Checked before the admin override so that future resource types without
        # an authorization adapter are always rejected, even for owners/admins.
        rule = "unknown_resource_type"
        if resource.resource_type is ResourceType.unknown:
            return _deny(DenyReason.unknown_resource_type, rule)
        trace.append(f"{rule}:pass")

        # ── Rule 5: Owner / admin override ──────────────────────────────────
        rule = "owner_admin_override"
        if subject.roles.intersection(_ADMIN_ROLES):
            return _allow(rule)
        trace.append(f"{rule}:pass")

        # ── Rule 6: Explicit resource deny ──────────────────────────────────
        rule = "explicit_resource_deny"
        if (
            subject.user_id in resource.explicit_deny_user_ids
            or _legacy_rule_matches(subject.resource_denies, resource.resource_type)
            or _legacy_rule_matches(resource.explicit_denies, resource.resource_type)
        ):
            return _deny(DenyReason.explicit_resource_deny, rule)
        trace.append(f"{rule}:pass")

        # ── Rule 7: Explicit resource allow ─────────────────────────────────
        rule = "explicit_resource_allow"
        if subject.user_id in resource.explicit_allow_user_ids or _legacy_rule_matches(
            subject.resource_grants, resource.resource_type
        ):
            return _allow(rule)
        trace.append(f"{rule}:pass")

        effective_permissions = subject.resolved_permissions
        if not effective_permissions:
            combined: set[str] = set()
            for role in subject.roles:
                combined.update(ROLE_PERMISSIONS.get(role, frozenset()))
            effective_permissions = frozenset(combined)

        # ── Rule 8: Collection allow ─────────────────────────────────────────
        rule = "collection_allow"
        if (
            resource.collection_ids
            and resource.resource_type in _COLLECTION_ELIGIBLE_TYPES
            and PermissionType.chat_use_collections in effective_permissions
        ):
            accessible = set(resource.subject_accessible_collection_ids)
            accessible.update(subject.accessible_collection_ids)
            if accessible.intersection(resource.collection_ids):
                return _allow(rule)
        trace.append(f"{rule}:pass")

        # ── Rule 9: Connector ACL ────────────────────────────────────────────
        rule = "connector_acl"
        if resource.connector_id is not None:
            if subject.user_id in resource.connector_allowed_user_ids or (
                resource.resource_id is not None
                and resource.resource_id in subject.connector_acl_item_ids
            ):
                return _allow(rule)
            if resource.connector_allowed_user_ids or subject.connector_acl_item_ids:
                # Non-empty ACL and subject is not in it.
                return _deny(DenyReason.connector_acl_denied, rule)
        trace.append(f"{rule}:pass")

        # ── Rule 10: Feature entitlement ────────────────────────────────────
        # Checked before role_permission so a disabled feature acts as a hard gate
        # for non-admin subjects. Admins bypass this via rule 5.
        rule = "feature_entitlement"
        if resource.feature_enabled is False:
            return _deny(DenyReason.feature_not_entitled, rule)
        trace.append(f"{rule}:pass")

        # ── Rule 11: Role / permission default ──────────────────────────────
        rule = "role_permission"
        required = _RESOURCE_ACTION_PERMISSIONS.get((resource.resource_type, action), frozenset())
        if required:
            if required.issubset(effective_permissions):
                return _allow(rule)
            missing = required - effective_permissions
            trace.append(f"{rule}:missing={','.join(sorted(missing))}")
            return _deny(DenyReason.insufficient_role, rule)
        trace.append(f"{rule}:pass(no_mapping)")

        # Default deny — no rule granted access.
        return _deny(DenyReason.insufficient_role, "default")

    def filter_accessible_resources(
        self,
        subject: SubjectContext,
        action: Action,
        resources: Sequence[ResourceContext],
        *,
        request_id: str | None = None,
    ) -> list[ResourceContext]:
        """Return the subset of resources the subject may perform action on."""
        rid = request_id or str(uuid.uuid4())
        return [
            r
            for r in resources
            if self.authorize(subject, action, r, request_id=rid).result is PermissionResult.allow
        ]

    def explain_decision(self, result: AuthorizationResult) -> str:
        """Return a human-readable, audit-friendly explanation of a decision."""
        resource_label = result.resource_type.value
        if result.resource_id:
            resource_label = f"{resource_label}/{result.resource_id}"

        lines = [
            f"Authorization: {result.result.upper()}",
            f"  subject    : {result.subject_id} (org={result.organization_id})",
            f"  action     : {result.action} on {resource_label}",
            f"  rule       : {result.matched_rule}",
            f"  request_id : {result.request_id}",
        ]
        if result.deny_reason:
            lines.append(f"  reason     : {result.deny_reason}")
        lines.append("  trace:")
        for step in result.trace:
            lines.append(f"    → {step}")
        return "\n".join(lines)
