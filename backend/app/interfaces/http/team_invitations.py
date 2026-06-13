from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.auth.passwords import PasswordHashConfig, build_password_hasher, hash_password
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.team.repositories.invitations import InvitationRepository
from app.domains.team.repositories.team import TeamRepository
from app.domains.team.schemas.invitations import (
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    OrganizationInvitationListResponse,
    OrganizationInvitationResponse,
    ResendInvitationResponse,
    RevokeInvitationResponse,
)
from app.domains.team.services.invitation_service import (
    can_resend,
    generate_invite_token,
    hash_invite_token,
    invite_expires_at,
    is_token_expired,
)
from app.models.organization import Organization
from app.models.organization_invitation import OrganizationInvitation
from app.models.permissions import PermissionType

router = APIRouter(prefix="/team/invitations", tags=["team"])
public_router = APIRouter(prefix="/team/invitations", tags=["team"])

invitation_repository = InvitationRepository()

_password_hasher = build_password_hasher(
    PasswordHashConfig(
        memory_cost=settings.app_auth_password_hash_memory_cost_kib,
        time_cost=settings.app_auth_password_hash_time_cost,
        parallelism=settings.app_auth_password_hash_parallelism,
        hash_length=settings.app_auth_password_hash_length,
        salt_length=settings.app_auth_password_salt_length,
    )
)
team_repository = TeamRepository()
audit_log_service = AuditLogService()
inv_logger = get_logger("events.team.invitations")


def _organization_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal organization context is invalid",
        ) from exc


def _user_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal user context is invalid",
        ) from exc


def _parse_invitation_id(invitation_id: str) -> UUID:
    try:
        return UUID(invitation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found"
        ) from exc


def _request_id(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


def _to_response(inv: OrganizationInvitation) -> OrganizationInvitationResponse:
    invited_by_name: str | None = None
    if inv.invited_by is not None:
        invited_by_name = (
            inv.invited_by.display_name
            or inv.invited_by.email
        )
    return OrganizationInvitationResponse(
        invitation_id=str(inv.id),
        organization_id=str(inv.organization_id),
        email=inv.email,
        role=inv.role,
        status=inv.status,
        expires_at=inv.expires_at,
        invited_by_name=invited_by_name,
        resend_count=inv.resend_count,
        last_sent_at=inv.last_sent_at,
        accepted_at=inv.accepted_at,
        revoked_at=inv.revoked_at,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
    )


@router.get("", response_model=OrganizationInvitationListResponse)
async def list_invitations(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_view)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrganizationInvitationListResponse:
    organization_id = _organization_id_from_principal(principal)

    invitations = await invitation_repository.list_pending(
        db_session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )
    total = await invitation_repository.count_pending(db_session, organization_id=organization_id)

    inv_logger.info(
        "team.invitations.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        total=total,
        returned=len(invitations),
    )
    return OrganizationInvitationListResponse(
        items=[_to_response(inv) for inv in invitations],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{invitation_id}/resend", response_model=ResendInvitationResponse)
async def resend_invitation(
    request: Request,
    invitation_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ResendInvitationResponse:
    organization_id = _organization_id_from_principal(principal)
    actor_user_id = _user_id_from_principal(principal)
    request_id_val = _request_id(request)
    parsed_id = _parse_invitation_id(invitation_id)

    inv = await invitation_repository.get(
        db_session,
        invitation_id=parsed_id,
        organization_id=organization_id,
    )
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if inv.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invitation is {inv.status} and cannot be resent",
        )
    if not can_resend(inv.last_sent_at):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait before resending this invitation",
        )

    new_token = generate_invite_token()
    new_token_hash = hash_invite_token(new_token)
    new_expires_at = invite_expires_at()

    await invitation_repository.mark_resent(
        db_session,
        invitation=inv,
        new_token_hash=new_token_hash,
        new_expires_at=new_expires_at,
    )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.invitation.resent",
        resource_type="organization_invitation",
        resource_id=inv.id,
        request_id=request_id_val,
        metadata={"resend_count": inv.resend_count},
    )
    await db_session.commit()

    # Re-fetch to get updated state (avoid sending stale inv data)
    updated_inv = await invitation_repository.get(
        db_session,
        invitation_id=parsed_id,
        organization_id=organization_id,
    )

    from app.workers.email_tasks import dispatch_email

    org_name = "Rudix"
    if updated_inv is not None and updated_inv.invited_by is not None:
        pass
    dispatch_email(
        organization_id=str(organization_id),
        user_id=str(actor_user_id),
        recipient_email=inv.email,
        event_type="invite_received",
        template_name="invite.html",
        subject="You've been invited to join Rudix",
        template_context={
            "org_name": org_name,
            "inviter_name": None,
            "role": inv.role,
            "accept_url": (
                str(settings.frontend_base_url).rstrip("/")
                + f"/accept-invite?token={new_token}"
            ),
            "recipient_name": inv.email.split("@")[0],
            "expiry_hours": 168,
        },
    )

    inv_logger.info(
        "team.invitation.resent",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        invitation_id=invitation_id,
    )
    return ResendInvitationResponse(invitation_id=invitation_id, resent=True)


@router.post("/{invitation_id}/revoke", response_model=RevokeInvitationResponse)
async def revoke_invitation(
    request: Request,
    invitation_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RevokeInvitationResponse:
    organization_id = _organization_id_from_principal(principal)
    actor_user_id = _user_id_from_principal(principal)
    request_id_val = _request_id(request)
    parsed_id = _parse_invitation_id(invitation_id)

    inv = await invitation_repository.get(
        db_session,
        invitation_id=parsed_id,
        organization_id=organization_id,
    )
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if inv.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Invitation is already {inv.status}",
        )

    await invitation_repository.mark_revoked(
        db_session,
        invitation=inv,
        revoked_by_user_id=actor_user_id,
    )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.invitation.revoked",
        resource_type="organization_invitation",
        resource_id=inv.id,
        request_id=request_id_val,
        metadata={},
    )
    await db_session.commit()

    inv_logger.info(
        "team.invitation.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        invitation_id=invitation_id,
    )
    return RevokeInvitationResponse(invitation_id=invitation_id, revoked=True)


@public_router.post("/accept", response_model=AcceptInvitationResponse)
async def accept_invitation(
    request: Request,
    payload: AcceptInvitationRequest,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AcceptInvitationResponse:
    token_hash = hash_invite_token(payload.token)
    request_id_val = _request_id(request)

    inv = await invitation_repository.get_by_token_hash(db_session, token_hash=token_hash)
    if inv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found or already used",
        )
    if inv.status == "accepted":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Invitation has already been accepted",
        )
    if inv.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invitation has been revoked",
        )
    if inv.status == "expired" or is_token_expired(inv.expires_at):
        if inv.status != "expired":
            inv.status = "expired"
            await db_session.flush()
            await db_session.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invitation has expired",
        )

    # Find the user and member created at invite time
    user = await team_repository.get_user_by_email(db_session, email=inv.email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invited user record not found",
        )

    org_name_row = await db_session.execute(
        select(Organization.name).where(Organization.id == inv.organization_id)
    )
    org_name = org_name_row.scalar_one_or_none()

    if payload.password:
        from datetime import UTC, datetime

        user.hashed_password = hash_password(payload.password, _password_hasher)
        user.password_state = "active"
        user.password_changed_at = datetime.now(UTC)
        user.failed_login_attempts = 0
        user.account_locked_at = None
        user.account_locked_until = None

    await invitation_repository.mark_accepted(
        db_session,
        invitation=inv,
        accepted_by_user_id=user.id,
    )

    await audit_log_service.record(
        db_session,
        organization_id=inv.organization_id,
        user_id=user.id,
        action="team.invitation.accepted",
        resource_type="organization_invitation",
        resource_id=inv.id,
        request_id=request_id_val,
        metadata={"role": inv.role, "password_set": bool(payload.password)},
    )
    await db_session.commit()

    inv_logger.info(
        "team.invitation.accepted",
        organization_id=str(inv.organization_id),
        invitation_id=str(inv.id),
        password_set=bool(payload.password),
    )
    return AcceptInvitationResponse(
        accepted=True,
        email=inv.email,
        role=inv.role,
        organization_name=org_name,
    )
