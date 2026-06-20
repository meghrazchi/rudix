"""Admin endpoints for F324: Access Debugger and Permission Simulator.

Endpoints
---------
GET  /admin/access-debugger/users     — search org members by name or email
POST /admin/access-debugger/simulate  — full DB-backed access simulation with audit log
"""

from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.auth.permission_service import PermissionService
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
from app.auth.resource_context_builder import (
    batch_get_explicit_denies,
    batch_get_explicit_grants,
    get_collection_ids_for_document,
    get_subject_accessible_collection_ids,
)
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.models.organization_member import OrganizationMember
from app.models.permissions import PermissionType
from app.models.user import User

router = APIRouter(prefix="/admin/access-debugger", tags=["access-debugger"])

_engine = PolicyEngine()
_perm_svc = PermissionService()
_audit = AuditLogService()
_logger = get_logger("events.access_debugger")


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _org_id(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid organization context",
        ) from exc


def _actor_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid principal context",
        ) from exc


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    header_rid = request.headers.get("x-request-id")
    return header_rid if header_rid else str(uuid.uuid4())


# ── Schema ─────────────────────────────────────────────────────────────────────


class OrgMemberResult(BaseModel):
    user_id: str
    display_name: str | None
    email: str
    role: str


class OrgMemberListResponse(BaseModel):
    items: list[OrgMemberResult]
    total: int


class SimulateAccessRequest(BaseModel):
    subject_user_id: str
    resource_type: str
    action: str
    resource_id: str | None = None


class TraceStep(BaseModel):
    rule: str
    outcome: str
    detail: str | None


class ReasonChainEntry(BaseModel):
    layer: str
    outcome: str
    detail: str | None


class TroubleshootingLink(BaseModel):
    label: str
    href: str


class SimulateAccessResponse(BaseModel):
    # Core decision
    decision: str
    extended_status: str
    matched_rule: str
    deny_reason: str | None
    # Subject
    subject_user_id: str
    subject_display_name: str | None
    subject_email: str
    subject_role: str
    # Resource
    resource_type: str
    resource_id: str | None
    action: str
    # Policy evaluation
    trace: list[TraceStep]
    reason_chain: list[ReasonChainEntry]
    # User permissions
    effective_permissions: list[str]
    # Guidance
    remediation: list[str]
    troubleshooting_links: list[TroubleshootingLink]
    # Audit
    request_id: str


# ── Internal helpers ───────────────────────────────────────────────────────────


_RULE_TO_LAYER: dict[str, str] = {
    "no_organization_context": "organization_membership",
    "tenant_boundary": "organization_membership",
    "system_deny": "system_policy",
    "unknown_resource_type": "system_policy",
    "owner_admin_override": "role",
    "explicit_resource_deny": "document_acl",
    "explicit_resource_allow": "document_acl",
    "collection_allow": "collection_policy",
    "connector_acl": "connector_acl",
    "feature_entitlement": "system_policy",
    "role_permission": "role",
}


def _parse_trace(raw_trace: list[str]) -> list[TraceStep]:
    steps: list[TraceStep] = []
    for entry in raw_trace:
        rule, sep, remainder = entry.partition(":")
        if not sep:
            steps.append(TraceStep(rule=entry, outcome="pass", detail=None))
        elif remainder == "allow":
            steps.append(TraceStep(rule=rule, outcome="allow", detail=None))
        elif remainder.startswith("deny("):
            reason_part = remainder[len("deny(") :].rstrip(")")
            steps.append(TraceStep(rule=rule, outcome="deny", detail=reason_part))
        elif remainder.startswith("pass"):
            detail = remainder[len("pass") :].lstrip("(").rstrip(")") or None
            steps.append(TraceStep(rule=rule, outcome="pass", detail=detail or None))
        else:
            steps.append(TraceStep(rule=rule, outcome="pass", detail=remainder or None))
    return steps


def _remediation_from_decision(
    decision: str,
    matched_rule: str,
    deny_reason: str | None,
    resource_type: str,
) -> list[str]:
    if decision == "allow":
        return []
    suggestions: list[str] = []
    if deny_reason == DenyReason.insufficient_role:
        suggestions.append(
            f"Grant the user a role with sufficient permissions for {resource_type} access."
        )
        suggestions.append("Use Admin > Access Management to add an explicit resource grant.")
    elif deny_reason == DenyReason.explicit_resource_deny:
        suggestions.append("An explicit deny overrides this user's role. Revoke the deny entry.")
        suggestions.append(
            "Go to Admin > Access Management > Resource Denies to find and remove it."
        )
    elif deny_reason == DenyReason.connector_acl_denied:
        suggestions.append(
            "The user is not in the connector ACL. Re-sync the connector or update ACL in the source system."
        )
    elif deny_reason == DenyReason.feature_not_entitled:
        suggestions.append(
            "The feature is disabled for this organisation. Enable it in feature flags."
        )
    elif deny_reason == DenyReason.collection_not_accessible:
        suggestions.append(
            "The resource is only accessible through a collection the user cannot access."
        )
        suggestions.append("Grant the user collection access or add an explicit resource grant.")
    elif deny_reason == DenyReason.no_organization_context:
        suggestions.append("The user must be a member of an organisation to access this resource.")
    elif deny_reason == DenyReason.tenant_boundary:
        suggestions.append(
            "This resource belongs to a different organisation — cross-tenant access is blocked."
        )
    else:
        suggestions.append("Review the user's role and any explicit grants or denies.")
    return suggestions


def _extended_status(result: AuthorizationResult) -> str:
    if result.result == PermissionResult.allow:
        if result.matched_rule == "collection_allow":
            return "inherited"
        return "allowed"
    if result.deny_reason == DenyReason.connector_acl_denied:
        return "restricted"
    if result.deny_reason in (DenyReason.feature_not_entitled, DenyReason.unknown_resource_type):
        return "unavailable"
    if result.deny_reason == DenyReason.no_organization_context:
        return "denied"
    if result.deny_reason == DenyReason.tenant_boundary:
        return "denied"
    return "denied"


def _build_reason_chain(trace: list[str]) -> list[ReasonChainEntry]:
    chain: list[ReasonChainEntry] = []
    for entry in trace:
        if ":allow" in entry:
            rule = entry.split(":allow")[0]
            chain.append(
                ReasonChainEntry(
                    layer=_RULE_TO_LAYER.get(rule, rule),
                    outcome="allow",
                    detail=None,
                )
            )
        elif ":deny(" in entry:
            rule = entry.split(":deny(")[0]
            reason_part = entry.split(":deny(")[-1].rstrip(")")
            chain.append(
                ReasonChainEntry(
                    layer=_RULE_TO_LAYER.get(rule, rule),
                    outcome="deny",
                    detail=reason_part,
                )
            )
        elif ":pass" in entry:
            rule = entry.split(":pass")[0]
            detail_part = entry.split(":pass")[-1].lstrip("(").rstrip(")") or None
            chain.append(
                ReasonChainEntry(
                    layer=_RULE_TO_LAYER.get(rule, rule),
                    outcome="pass",
                    detail=detail_part or None,
                )
            )
    return chain


def _troubleshooting_links(
    resource_type: str, resource_id: str | None
) -> list[TroubleshootingLink]:
    links: list[TroubleshootingLink] = [
        TroubleshootingLink(label="View audit logs", href="/admin/audit-logs"),
        TroubleshootingLink(label="View access management", href="/admin/permissions"),
    ]
    if resource_id:
        if resource_type == "document":
            links.append(
                TroubleshootingLink(label="View document details", href=f"/documents/{resource_id}")
            )
        elif resource_type == "collection":
            links.append(
                TroubleshootingLink(label="View collection", href=f"/collections/{resource_id}")
            )
        elif resource_type in ("connector", "connector_source_item"):
            links.append(
                TroubleshootingLink(
                    label="View connector sync status", href=f"/connectors/{resource_id}"
                )
            )
        elif resource_type in ("graph_entity", "graph_evidence"):
            links.append(
                TroubleshootingLink(
                    label="View graph entity", href=f"/graph/entities/{resource_id}"
                )
            )
    return links


# ── User search ────────────────────────────────────────────────────────────────


@router.get("/users", response_model=OrgMemberListResponse)
async def search_org_users(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.security_center_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
) -> OrgMemberListResponse:
    """Search organization members by display name or email for user selector."""
    organization_id = _org_id(principal)

    base_stmt = (
        select(User, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(OrganizationMember.organization_id == organization_id)
    )

    search = q.strip()
    if search:
        pattern = f"%{search}%"
        base_stmt = base_stmt.where(
            or_(
                User.email.ilike(pattern),
                User.display_name.ilike(pattern),
            )
        )

    result = await db.execute(base_stmt.limit(limit))
    rows = result.all()

    items = [
        OrgMemberResult(
            user_id=str(user.id),
            display_name=user.display_name,
            email=user.email,
            role=role,
        )
        for user, role in rows
    ]
    return OrgMemberListResponse(items=items, total=len(items))


# ── Simulate access ────────────────────────────────────────────────────────────


@router.post("/simulate", response_model=SimulateAccessResponse)
async def simulate_access(
    request: Request,
    payload: SimulateAccessRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.security_center_view)),
    ],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> SimulateAccessResponse:
    """Simulate the full policy engine against a user/resource/action triple.

    Loads real ACL metadata from the database (grants, denies, collection
    memberships, connector ACLs) so the result matches production behavior.
    Audit-logs every simulation. Never exposes resource content.
    """
    organization_id = _org_id(principal)
    actor_id = _actor_id(principal)
    rid = _request_id(request)

    # Validate enums
    try:
        rt = ResourceType(payload.resource_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown resource_type: {payload.resource_type}",
        ) from exc

    try:
        act = Action(payload.action)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown action: {payload.action}",
        ) from exc

    # Resolve subject membership
    try:
        subject_uuid = UUID(payload.subject_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="subject_user_id must be a valid UUID",
        ) from exc

    member_row = await db.scalar(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == subject_uuid,
        )
    )
    if member_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subject user is not a member of this organisation",
        )

    user_row = await db.get(User, subject_uuid)
    if user_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subject user not found",
        )

    # Resolve the subject's full permission set
    resolved_perms = await _perm_svc.get_user_permissions(
        db,
        roles=[member_row.role],
        custom_role_id=member_row.custom_role_id,
    )

    subject = SubjectContext(
        user_id=payload.subject_user_id,
        organization_id=str(organization_id),
        roles=frozenset([member_row.role]),
        resolved_permissions=resolved_perms,
    )

    # Build ResourceContext with real DB lookups
    collection_ids: list[str] = []
    subject_accessible_collection_ids: list[str] = []
    explicit_allow_user_ids: list[str] = []
    explicit_deny_user_ids: list[str] = []

    resource_id_str = payload.resource_id

    if resource_id_str:
        try:
            resource_uuid = UUID(resource_id_str)
        except ValueError:
            resource_uuid = None

        if resource_uuid and rt == ResourceType.document:
            collection_ids = await get_collection_ids_for_document(db, document_id=resource_uuid)

        # Load explicit grants / denies for this specific resource
        grants_map = await batch_get_explicit_grants(
            db,
            organization_id=organization_id,
            resource_type=rt,
            resource_ids=[resource_id_str],
        )
        denies_map = await batch_get_explicit_denies(
            db,
            organization_id=organization_id,
            resource_type=rt,
            resource_ids=[resource_id_str],
        )
        explicit_allow_user_ids = grants_map.get(resource_id_str, [])
        explicit_deny_user_ids = denies_map.get(resource_id_str, [])

    # Subject's accessible collections (for collection_allow rule)
    subject_accessible_collection_ids = await get_subject_accessible_collection_ids(
        db,
        organization_id=organization_id,
        user_id=subject_uuid,
        user_roles=[member_row.role],
    )

    resource = ResourceContext(
        resource_type=rt,
        resource_id=resource_id_str,
        organization_id=str(organization_id),
        collection_ids=collection_ids,
        explicit_allow_user_ids=explicit_allow_user_ids,
        explicit_deny_user_ids=explicit_deny_user_ids,
        subject_accessible_collection_ids=subject_accessible_collection_ids,
    )

    # Run policy engine
    result = _engine.authorize(subject, act, resource, request_id=rid)

    # Audit-log the simulation
    await _audit.record(
        db,
        organization_id=organization_id,
        user_id=actor_id,
        action="access_debugger.simulate",
        resource_type=payload.resource_type,
        resource_id=UUID(resource_id_str) if resource_id_str else None,
        request_id=rid,
        metadata={
            "subject_user_id": payload.subject_user_id,
            "action": payload.action,
            "decision": result.result.value,
            "matched_rule": result.matched_rule,
            "deny_reason": result.deny_reason.value if result.deny_reason else None,
        },
    )
    await db.commit()

    _logger.info(
        "access_debugger.simulate",
        organization_id=str(organization_id),
        actor_id=str(actor_id),
        subject_user_id=payload.subject_user_id,
        resource_type=payload.resource_type,
        resource_id=resource_id_str,
        action=payload.action,
        decision=result.result.value,
    )

    trace_steps = [
        TraceStep(rule=s.rule, outcome=s.outcome, detail=s.detail)
        for s in _parse_trace(result.trace)
    ]
    reason_chain = _build_reason_chain(result.trace)
    remediation = _remediation_from_decision(
        result.result.value,
        result.matched_rule,
        result.deny_reason.value if result.deny_reason else None,
        payload.resource_type,
    )
    links = _troubleshooting_links(payload.resource_type, resource_id_str)

    return SimulateAccessResponse(
        decision=result.result.value,
        extended_status=_extended_status(result),
        matched_rule=result.matched_rule,
        deny_reason=result.deny_reason.value if result.deny_reason else None,
        subject_user_id=payload.subject_user_id,
        subject_display_name=user_row.display_name,
        subject_email=user_row.email,
        subject_role=member_row.role,
        resource_type=payload.resource_type,
        resource_id=resource_id_str,
        action=payload.action,
        trace=trace_steps,
        reason_chain=reason_chain,
        effective_permissions=sorted(resolved_perms),
        remediation=remediation,
        troubleshooting_links=links,
        request_id=rid,
    )
