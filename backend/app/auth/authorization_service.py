"""High-level async authorization service — F330.

Wraps PolicyEngine with DB-assisted resolution: resolves custom-role permissions,
feature-flag state, and collection membership before delegating to the engine.

Usage (FastAPI route):

    from app.auth.authorization_service import AuthorizationService
    from app.auth.policy_engine import Action, ResourceContext, ResourceType

    svc = AuthorizationService()

    result = await svc.authorize(
        principal,
        action=Action.view,
        resource=ResourceContext(
            resource_type=ResourceType.document,
            resource_id=str(doc.id),
            organization_id=str(doc.organization_id),
        ),
        db_session=db_session,
    )
    if result.result is PermissionResult.deny:
        raise HTTPException(status_code=403, detail="Access denied")
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.auth.permission_service import PermissionService
from app.auth.policy_engine import (
    Action,
    AuthorizationResult,
    PermissionResult,
    PolicyEngine,
    ResourceContext,
    SubjectContext,
)
from app.db.session import SessionLocal
from app.domains.admin.audit_events import AUTHZ_ACCESS_DENIED
from app.domains.admin.services.audit_service import AuditLogService
from app.models.organization_member import OrganizationMember

_engine = PolicyEngine()
_permission_service = PermissionService()
_audit_log_service = AuditLogService()


class AuthorizationService:
    """Async wrapper around PolicyEngine that resolves DB-backed context.

    A single shared instance is safe to use across requests.
    """

    async def _build_subject(
        self,
        principal: AuthenticatedPrincipal,
        db_session: AsyncSession,
    ) -> SubjectContext:
        if principal.api_key_permissions is not None:
            return SubjectContext(
                user_id=principal.user_id,
                organization_id=principal.organization_id,
                roles=frozenset(),
                resolved_permissions=principal.api_key_permissions,
                is_api_key=True,
            )

        custom_role_id = None
        if principal.organization_id:
            try:
                org_uuid = uuid.UUID(principal.organization_id)
                user_uuid = uuid.UUID(principal.user_id)
                row = await db_session.scalar(
                    select(OrganizationMember.custom_role_id).where(
                        OrganizationMember.organization_id == org_uuid,
                        OrganizationMember.user_id == user_uuid,
                    )
                )
                custom_role_id = row
            except ValueError:
                pass

        resolved = await _permission_service.get_user_permissions(
            db_session,
            roles=list(principal.roles),
            custom_role_id=custom_role_id,
        )
        return SubjectContext(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            roles=frozenset(principal.roles),
            resolved_permissions=resolved,
        )

    async def authorize(
        self,
        principal: AuthenticatedPrincipal,
        action: Action,
        resource: ResourceContext,
        db_session: AsyncSession,
        *,
        request_id: str | None = None,
    ) -> AuthorizationResult:
        """Resolve subject context from the DB then evaluate the policy engine."""
        subject = await self._build_subject(principal, db_session)
        return _engine.authorize(subject, action, resource, request_id=request_id)

    async def filter_accessible_resources(
        self,
        principal: AuthenticatedPrincipal,
        action: Action,
        resources: Sequence[ResourceContext],
        db_session: AsyncSession,
        *,
        request_id: str | None = None,
    ) -> list[ResourceContext]:
        """Return only the resources the principal can perform action on."""
        if not resources:
            return []
        subject = await self._build_subject(principal, db_session)
        rid = request_id or str(uuid.uuid4())
        return _engine.filter_accessible_resources(subject, action, resources, request_id=rid)

    async def authorize_or_raise(
        self,
        principal: AuthenticatedPrincipal,
        action: Action,
        resource: ResourceContext,
        db_session: AsyncSession,
        *,
        request_id: str | None = None,
        # Use 404 to avoid revealing existence of denied resources to non-admins.
        deny_status: int = status.HTTP_404_NOT_FOUND,
        deny_detail: str = "Resource not found",
    ) -> AuthorizationResult:
        """Authorize and raise an HTTPException on deny.

        Uses 404 by default so callers don't reveal resource existence to
        unauthorized subjects. Pass deny_status=403 when existence is already
        known (e.g. admin endpoints, mutation paths that validated first).
        """
        result = await self.authorize(
            principal, action, resource, db_session, request_id=request_id
        )
        if result.result is PermissionResult.deny:
            await self._record_deny(principal, action, resource, result)
            raise HTTPException(status_code=deny_status, detail=deny_detail)
        return result

    async def _record_deny(
        self,
        principal: AuthenticatedPrincipal,
        action: Action,
        resource: ResourceContext,
        result: AuthorizationResult,
    ) -> None:
        """Best-effort audit write for a denied access attempt.

        Uses its own short-lived session/transaction rather than the caller's
        `db_session`: the caller's session is never committed on this path
        (it immediately raises an HTTPException), so writing through it would
        silently roll the audit row back. Never raises — a broken audit
        pipeline must not break authorization.
        """
        if principal.organization_id is None:
            # Rule 1 (no_organization_context) denies precisely when there's
            # no org to scope an audit row to — nothing meaningful to record.
            return
        try:
            async with SessionLocal() as audit_session:
                await _audit_log_service.record(
                    audit_session,
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    action=AUTHZ_ACCESS_DENIED,
                    resource_type=str(resource.resource_type),
                    resource_id=resource.resource_id,
                    metadata={
                        "action": action.value,
                        "deny_reason": result.deny_reason.value if result.deny_reason else None,
                        "matched_rule": result.matched_rule,
                        "request_id": result.request_id,
                    },
                )
                await audit_session.commit()
        except Exception:
            pass

    def explain_decision(self, result: AuthorizationResult) -> str:
        return _engine.explain_decision(result)
