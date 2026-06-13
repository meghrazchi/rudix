from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import require_permission
from app.auth.passwords import PasswordHashConfig, build_password_hasher, hash_password
from app.core.config import settings
from app.models.permissions import PermissionType
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.team.repositories.invitations import InvitationRepository
from app.domains.team.repositories.team import TeamRepository
from app.domains.team.schemas.team import (
    InviteTeamMemberRequest,
    InviteTeamMemberResponse,
    SetMemberPasswordRequest,
    SetMemberPasswordResponse,
    TeamMemberDetailResponse,
    TeamMemberListResponse,
    TeamMemberRemoveResponse,
    TeamMemberResponse,
    UpdateTeamMemberRoleRequest,
)
from app.domains.team.services.invitation_service import (
    generate_invite_token,
    hash_invite_token,
    invite_expires_at,
)
from app.domains.team.services.team_service import TeamService
from app.models.auth_session import AuthRefreshSession
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

router = APIRouter(prefix="/team", tags=["team"])
team_repository = TeamRepository()
invitation_repository = InvitationRepository()
team_service = TeamService()
audit_log_service = AuditLogService()
team_logger = get_logger("events.team")

_password_hasher = build_password_hasher(
    PasswordHashConfig(
        memory_cost=settings.app_auth_password_hash_memory_cost_kib,
        time_cost=settings.app_auth_password_hash_time_cost,
        parallelism=settings.app_auth_password_hash_parallelism,
        hash_length=settings.app_auth_password_hash_length,
        salt_length=settings.app_auth_password_salt_length,
    )
)


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


def _parse_member_id(member_id: str) -> UUID:
    try:
        return UUID(member_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Member not found"
        ) from exc


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


def _to_member_response(member: OrganizationMember) -> TeamMemberResponse:
    user = member.user
    email = user.email if user is not None else "unknown@example.com"
    return TeamMemberResponse(
        member_id=str(member.id),
        user_id=str(member.user_id),
        name=team_service.resolve_member_name(user),
        email=email,
        role=member.role,
        custom_role_id=str(member.custom_role_id) if member.custom_role_id else None,
        status=team_service.resolve_member_status(member),
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def _to_member_detail_response(member: OrganizationMember) -> TeamMemberDetailResponse:
    user = member.user
    email = user.email if user is not None else "unknown@example.com"
    return TeamMemberDetailResponse(
        member_id=str(member.id),
        user_id=str(member.user_id),
        name=team_service.resolve_member_name(user),
        email=email,
        role=member.role,
        custom_role_id=str(member.custom_role_id) if member.custom_role_id else None,
        status=team_service.resolve_member_status(member),
        is_active=user.is_active if user is not None else False,
        provisioned_by=user.provisioned_by if user is not None else "manual",
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


async def _count_owners(session: AsyncSession, *, organization_id: UUID) -> int:
    result = await session.execute(
        select(func.count(OrganizationMember.id)).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == OrganizationRole.owner.value,
        )
    )
    return int(result.scalar_one())


async def _revoke_user_sessions(
    session: AsyncSession,
    *,
    user_id: UUID,
    organization_id: UUID,
    reason: str,
) -> int:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    result = await session.execute(
        select(AuthRefreshSession).where(
            AuthRefreshSession.user_id == user_id,
            AuthRefreshSession.organization_id == organization_id,
            AuthRefreshSession.revoked_at.is_(None),
        )
    )
    sessions = list(result.scalars().all())
    for sess in sessions:
        sess.revoked_at = now
        sess.revoked_reason = reason
    await session.flush()
    return len(sessions)


@router.get("/members", response_model=TeamMemberListResponse)
async def list_team_members(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_view)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    search: Annotated[str | None, Query(max_length=255)] = None,
    role: Annotated[str | None, Query()] = None,
    member_status: Annotated[str | None, Query(alias="status")] = None,
) -> TeamMemberListResponse:
    organization_id = _organization_id_from_principal(principal)

    base_query = (
        select(OrganizationMember)
        .where(OrganizationMember.organization_id == organization_id)
        .options(selectinload(OrganizationMember.user))
    )
    count_query = select(func.count(OrganizationMember.id)).where(
        OrganizationMember.organization_id == organization_id
    )

    if search:
        term = f"%{search.strip()}%"
        search_filter = or_(
            User.email.ilike(term),
            User.display_name.ilike(term),
        )
        base_query = base_query.join(User, OrganizationMember.user_id == User.id).where(search_filter)
        count_query = count_query.join(User, OrganizationMember.user_id == User.id).where(search_filter)

    if role:
        base_query = base_query.where(OrganizationMember.role == role)
        count_query = count_query.where(OrganizationMember.role == role)

    members_result = await db_session.execute(
        base_query.order_by(OrganizationMember.created_at.asc(), OrganizationMember.id.asc())
        .offset(offset)
        .limit(limit)
    )
    members = list(members_result.scalars().all())

    if member_status == "invited":
        members = [m for m in members if team_service.resolve_member_status(m) == "invited"]
    elif member_status == "active":
        members = [m for m in members if team_service.resolve_member_status(m) == "active"]

    total_result = await db_session.execute(count_query)
    total = int(total_result.scalar_one())

    items = [_to_member_response(member) for member in members]

    team_logger.info(
        "team.members.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
    )
    return TeamMemberListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/members/{member_id}", response_model=TeamMemberDetailResponse)
async def get_team_member(
    member_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_view)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TeamMemberDetailResponse:
    organization_id = _organization_id_from_principal(principal)
    parsed_member_id = _parse_member_id(member_id)

    member = await team_repository.get_member(
        db_session,
        member_id=parsed_member_id,
        organization_id=organization_id,
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    return _to_member_detail_response(member)


@router.post(
    "/members/invite", response_model=InviteTeamMemberResponse, status_code=status.HTTP_201_CREATED
)
async def invite_team_member(
    request: Request,
    payload: InviteTeamMemberRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InviteTeamMemberResponse:
    organization_id = _organization_id_from_principal(principal)
    actor_user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    normalized_email = team_service.normalize_email(payload.email)

    user = await team_repository.get_user_by_email(db_session, email=normalized_email)
    invited = False
    resolved_name = payload.name or team_service.display_name_for_email(normalized_email)

    if user is None:
        invited = True
        user = await team_repository.create_user(
            db_session,
            organization_id=organization_id,
            external_auth_id=team_service.invited_external_auth_id(),
            email=normalized_email,
            display_name=resolved_name,
        )
    elif payload.name and user.display_name != payload.name:
        user.display_name = payload.name
        await db_session.flush()

    member = await team_repository.get_member_for_user(
        db_session,
        organization_id=organization_id,
        user_id=user.id,
    )
    if member is None:
        member = await team_repository.create_member(
            db_session,
            organization_id=organization_id,
            user_id=user.id,
            role=payload.role,
        )
        invited = True
    elif member.role != OrganizationRole.owner.value and member.role != payload.role:
        member.role = payload.role
        await db_session.flush()

    member = await team_repository.get_member(
        db_session,
        member_id=member.id,
        organization_id=organization_id,
    )
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load invited member",
        )

    # Create invitation record with hashed token
    invite_token = generate_invite_token()
    token_hash = hash_invite_token(invite_token)
    expires_at = invite_expires_at()

    # Revoke any existing pending invitation for this email
    existing_inv = await invitation_repository.get_pending_by_email(
        db_session,
        organization_id=organization_id,
        email=normalized_email,
    )
    if existing_inv is not None:
        existing_inv.status = "revoked"
        await db_session.flush()

    await invitation_repository.create(
        db_session,
        organization_id=organization_id,
        email=normalized_email,
        role=payload.role,
        token_hash=token_hash,
        expires_at=expires_at,
        invited_by_user_id=actor_user_id,
        member_id=member.id,
    )

    org_name_row = await db_session.execute(
        select(Organization.name).where(Organization.id == organization_id)
    )
    org_name = org_name_row.scalar_one_or_none() or "Rudix"

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.member.invited",
        resource_type="organization_member",
        resource_id=member.id,
        request_id=request_id,
        metadata={
            "role": payload.role,
            "invited": invited,
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await db_session.commit()

    from app.workers.email_tasks import dispatch_email

    dispatch_email(
        organization_id=str(organization_id),
        user_id=str(user.id),
        recipient_email=normalized_email,
        event_type="invite_received",
        template_name="invite.html",
        subject=f"You've been invited to join {org_name}",
        template_context={
            "org_name": org_name,
            "inviter_name": None,
            "role": payload.role,
            "accept_url": (
                str(settings.frontend_base_url).rstrip("/")
                + f"/accept-invite?token={invite_token}"
            ),
            "recipient_name": resolved_name,
            "expiry_hours": 168,
        },
    )

    team_logger.info(
        "team.member.invited",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_201_CREATED,
        member_id=str(member.id),
        invited=invited,
    )
    return InviteTeamMemberResponse(member=_to_member_response(member), invited=invited)


@router.patch("/members/{member_id}/role", response_model=TeamMemberResponse)
async def update_team_member_role(
    request: Request,
    member_id: str,
    payload: UpdateTeamMemberRoleRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TeamMemberResponse:
    organization_id = _organization_id_from_principal(principal)
    actor_user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    parsed_member_id = _parse_member_id(member_id)

    member = await team_repository.get_member(
        db_session,
        member_id=parsed_member_id,
        organization_id=organization_id,
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if member.role == OrganizationRole.owner.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Owner role cannot be changed",
        )

    if payload.role is None and payload.custom_role_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either role or custom_role_id must be provided",
        )

    previous_role = member.role

    if payload.custom_role_id is not None:
        try:
            from uuid import UUID as _UUID
            custom_role_uuid = _UUID(payload.custom_role_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="custom_role_id is not a valid UUID",
            ) from exc
        member.custom_role_id = custom_role_uuid
        if payload.role:
            member.role = payload.role
    else:
        member.role = payload.role  # type: ignore[assignment]
        member.custom_role_id = None

    await db_session.flush()

    # Revoke sessions if role is being downgraded to a less privileged role
    privileged_roles = {OrganizationRole.owner.value, OrganizationRole.admin.value}
    new_role = payload.role or member.role
    if previous_role in privileged_roles and new_role not in privileged_roles:
        revoked_count = await _revoke_user_sessions(
            db_session,
            user_id=member.user_id,
            organization_id=organization_id,
            reason="role_downgrade",
        )
        team_logger.info(
            "team.member.sessions.revoked",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            member_id=str(member.id),
            revoked_sessions=revoked_count,
            reason="role_downgrade",
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.member.role.updated",
        resource_type="organization_member",
        resource_id=member.id,
        request_id=request_id,
        metadata={
            "previous_role": previous_role,
            "role": payload.role,
            "custom_role_id": payload.custom_role_id,
            "status_code": status.HTTP_200_OK,
        },
    )
    await db_session.commit()

    member = await team_repository.get_member(
        db_session,
        member_id=parsed_member_id,
        organization_id=organization_id,
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    team_logger.info(
        "team.member.role.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        member_id=str(member.id),
        role=payload.role,
    )
    return _to_member_response(member)


@router.post("/members/{member_id}/deactivate", response_model=TeamMemberDetailResponse)
async def deactivate_team_member(
    request: Request,
    member_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TeamMemberDetailResponse:
    organization_id = _organization_id_from_principal(principal)
    actor_user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    parsed_member_id = _parse_member_id(member_id)

    member = await team_repository.get_member(
        db_session,
        member_id=parsed_member_id,
        organization_id=organization_id,
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if member.role == OrganizationRole.owner.value:
        owner_count = await _count_owners(db_session, organization_id=organization_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot deactivate the last owner",
            )

    user = member.user
    if user is not None:
        user.is_active = False
        await db_session.flush()
        revoked_count = await _revoke_user_sessions(
            db_session,
            user_id=member.user_id,
            organization_id=organization_id,
            reason="member_deactivated",
        )
        team_logger.info(
            "team.member.sessions.revoked",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            member_id=str(member.id),
            revoked_sessions=revoked_count,
            reason="member_deactivated",
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.member.deactivated",
        resource_type="organization_member",
        resource_id=member.id,
        request_id=request_id,
        metadata={"status_code": status.HTTP_200_OK},
    )
    await db_session.commit()

    member = await team_repository.get_member(
        db_session,
        member_id=parsed_member_id,
        organization_id=organization_id,
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    team_logger.info(
        "team.member.deactivated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        member_id=member_id,
    )
    return _to_member_detail_response(member)


@router.post("/members/{member_id}/set-password", response_model=SetMemberPasswordResponse)
async def set_member_password(
    request: Request,
    member_id: str,
    payload: SetMemberPasswordRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SetMemberPasswordResponse:
    from datetime import UTC, datetime

    organization_id = _organization_id_from_principal(principal)
    actor_user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    parsed_member_id = _parse_member_id(member_id)

    member = await team_repository.get_member(
        db_session,
        member_id=parsed_member_id,
        organization_id=organization_id,
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    user = member.user
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User record not found")

    user.hashed_password = hash_password(payload.password, _password_hasher)
    user.password_state = "active"
    user.password_changed_at = datetime.now(UTC)
    user.failed_login_attempts = 0
    user.account_locked_at = None
    user.account_locked_until = None

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.member.password_set",
        resource_type="organization_member",
        resource_id=member.id,
        request_id=request_id,
        metadata={},
    )
    await db_session.commit()

    team_logger.info(
        "team.member.password_set",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        member_id=member_id,
    )
    return SetMemberPasswordResponse(member_id=member_id)


@router.delete("/members/{member_id}", response_model=TeamMemberRemoveResponse)
async def remove_team_member(
    request: Request,
    member_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.team_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TeamMemberRemoveResponse:
    organization_id = _organization_id_from_principal(principal)
    actor_user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    parsed_member_id = _parse_member_id(member_id)

    member = await team_repository.get_member(
        db_session,
        member_id=parsed_member_id,
        organization_id=organization_id,
    )
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if member.role == OrganizationRole.owner.value:
        owner_count = await _count_owners(db_session, organization_id=organization_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot remove the last owner",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Owner cannot be removed",
        )

    # Revoke sessions before deleting member
    if member.user_id is not None:
        revoked_count = await _revoke_user_sessions(
            db_session,
            user_id=member.user_id,
            organization_id=organization_id,
            reason="member_removed",
        )
        team_logger.info(
            "team.member.sessions.revoked",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            member_id=str(member.id),
            revoked_sessions=revoked_count,
            reason="member_removed",
        )

    await team_repository.delete_member(db_session, member=member)
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.member.removed",
        resource_type="organization_member",
        resource_id=parsed_member_id,
        request_id=request_id,
        metadata={"status_code": status.HTTP_200_OK},
    )
    await db_session.commit()

    team_logger.info(
        "team.member.removed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        member_id=member_id,
    )
    return TeamMemberRemoveResponse(removed=True)
