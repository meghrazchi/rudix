from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_principal, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.db.session import get_db_session
from app.models.governance import OrganizationGovernancePolicy
from app.models.org_sso_config import OrgSSOConfig
from app.models.usage import AuditLog

router = APIRouter(prefix="/security", tags=["security"])

_ADMIN_ROLES = ("owner", "admin")


# ── Response schemas ──────────────────────────────────────────────────────────

class SessionItem(BaseModel):
    id: str
    device: str
    ip_address: str | None
    location: str | None
    created_at: str | None
    last_active_at: str | None
    is_current: bool


class SessionList(BaseModel):
    items: list[SessionItem]


class SecurityPosture(BaseModel):
    prompt_injection_protection: bool | None
    citation_validation: bool | None
    tenant_isolation: bool | None
    output_validation: bool | None
    tool_policy_enforced: bool | None
    last_audit_at: str | None


class LoginPolicy(BaseModel):
    domain_allowlist: list[str]
    session_timeout_hours: int | None
    sso_required: bool
    invite_only: bool
    mfa_required: bool


class LoginPolicyPatch(BaseModel):
    domain_allowlist: list[str] | None = None
    session_timeout_hours: int | None = None
    sso_required: bool | None = None
    invite_only: bool | None = None
    mfa_required: bool | None = None


class AuditEventItem(BaseModel):
    id: str
    event_type: str
    actor_email: str | None
    created_at: str
    summary: str


class AuditEventList(BaseModel):
    items: list[AuditEventItem]
    total: int


# ── Private helpers ───────────────────────────────────────────────────────────

def _parse_device(user_agent: str | None) -> str:
    if not user_agent:
        return "Unknown device"
    ua = user_agent.lower()
    if "chrome" in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua:
        browser = "Safari"
    elif "edge" in ua:
        browser = "Edge"
    else:
        browser = "Browser"
    if "windows" in ua:
        os_name = "Windows"
    elif "mac" in ua:
        os_name = "macOS"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua:
        os_name = "iOS"
    elif "linux" in ua:
        os_name = "Linux"
    else:
        os_name = "Unknown OS"
    return f"{browser} on {os_name}"


_VERB_MAP = {
    "create": "created",
    "update": "updated",
    "delete": "deleted",
    "read": "accessed",
    "answer": "answered",
    "upload": "uploaded",
    "index": "indexed",
    "login": "signed in",
    "logout": "signed out",
    "revoke": "revoked",
    "invite": "invited",
}


def _audit_summary(action: str, resource_type: str) -> str:
    verb = action.split(".")[-1]
    resource = resource_type.replace("_", " ").title()
    friendly = _VERB_MAP.get(verb.lower(), verb)
    return f"{resource} {friendly}"


async def _load_sso(db: AsyncSession, org_uuid: UUID) -> OrgSSOConfig | None:
    result = await db.execute(
        select(OrgSSOConfig).where(OrgSSOConfig.organization_id == org_uuid)
    )
    return result.scalar_one_or_none()


def _policy_from_sso(sso: OrgSSOConfig | None) -> LoginPolicy:
    domain_allowlist: list[str] = []
    sso_required = False
    if sso and sso.enabled:
        sso_required = True
        if sso.domain:
            domain_allowlist = [sso.domain]
    return LoginPolicy(
        domain_allowlist=domain_allowlist,
        session_timeout_hours=None,
        sso_required=sso_required,
        invite_only=False,
        mfa_required=False,
    )


# ── GET /security/sessions ────────────────────────────────────────────────────

@router.get("/sessions", response_model=SessionList)
async def get_sessions(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> SessionList:
    ip = request.client.host if request.client else None
    device = _parse_device(request.headers.get("user-agent"))
    now_iso = datetime.now(UTC).isoformat()
    return SessionList(
        items=[
            SessionItem(
                id=principal.user_id,
                device=device,
                ip_address=ip,
                location=None,
                created_at=None,
                last_active_at=now_iso,
                is_current=True,
            )
        ]
    )


# ── DELETE /security/sessions/{session_id} ────────────────────────────────────

@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> None:
    if session_id == principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot revoke the current session — use logout instead.",
        )
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")


# ── POST /security/sessions/revoke-all ───────────────────────────────────────

@router.post("/sessions/revoke-all")
async def revoke_all_other_sessions(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> dict:
    return {"revoked_count": 0}


# ── GET /security/login-policy ────────────────────────────────────────────────

@router.get("/login-policy", response_model=LoginPolicy)
async def get_login_policy(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> LoginPolicy:
    sso = None
    if principal.organization_id:
        sso = await _load_sso(db, UUID(principal.organization_id))
    return _policy_from_sso(sso)


# ── PATCH /security/login-policy ─────────────────────────────────────────────

@router.patch("/login-policy", response_model=LoginPolicy)
async def update_login_policy(
    body: LoginPolicyPatch,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> LoginPolicy:
    sso = None
    if principal.organization_id and body.sso_required is not None:
        sso = await _load_sso(db, UUID(principal.organization_id))
        if sso:
            sso.enabled = body.sso_required
            await db.commit()
            await db.refresh(sso)
    elif principal.organization_id:
        sso = await _load_sso(db, UUID(principal.organization_id))
    return _policy_from_sso(sso)


# ── GET /security/posture ─────────────────────────────────────────────────────

@router.get("/posture", response_model=SecurityPosture)
async def get_security_posture(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> SecurityPosture:
    tool_policy_enforced: bool | None = None
    last_audit_at: str | None = None

    if principal.organization_id:
        org_uuid = UUID(principal.organization_id)

        gov_row = await db.execute(
            select(OrganizationGovernancePolicy).where(
                OrganizationGovernancePolicy.organization_id == org_uuid
            )
        )
        gov = gov_row.scalar_one_or_none()
        if gov is not None:
            tool_policy_enforced = gov.admin_only_model_selection

        last_row = await db.execute(
            select(AuditLog.created_at)
            .where(AuditLog.organization_id == org_uuid)
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        last_ts = last_row.scalar_one_or_none()
        if last_ts is not None:
            last_audit_at = last_ts.isoformat()

    return SecurityPosture(
        prompt_injection_protection=settings.agent_prompt_injection_guard_enabled,
        citation_validation=True,
        tenant_isolation=True,
        output_validation=True,
        tool_policy_enforced=tool_policy_enforced,
        last_audit_at=last_audit_at,
    )


# ── GET /security/audit-events ────────────────────────────────────────────────

@router.get("/audit-events", response_model=AuditEventList)
async def get_audit_events(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=5, ge=1, le=50),
) -> AuditEventList:
    if not principal.organization_id:
        return AuditEventList(items=[], total=0)

    org_uuid = UUID(principal.organization_id)

    rows = await db.execute(
        select(AuditLog)
        .options(selectinload(AuditLog.user))
        .where(AuditLog.organization_id == org_uuid)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    logs = rows.scalars().all()

    count_row = await db.execute(
        select(func.count(AuditLog.id)).where(AuditLog.organization_id == org_uuid)
    )
    total: int = count_row.scalar_one() or 0

    items = [
        AuditEventItem(
            id=str(log.id),
            event_type=log.action,
            actor_email=log.user.email if log.user else None,
            created_at=log.created_at.isoformat(),
            summary=_audit_summary(log.action, log.resource_type),
        )
        for log in logs
    ]

    return AuditEventList(items=items, total=total)
