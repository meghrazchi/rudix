from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.team.repositories.team import TeamRepository
from app.domains.team.schemas.team import (
    InviteTeamMemberRequest,
    InviteTeamMemberResponse,
    TeamMemberListResponse,
    TeamMemberRemoveResponse,
    TeamMemberResponse,
    UpdateTeamMemberRoleRequest,
)
from app.domains.team.services.team_service import TeamService
from app.models.enums import OrganizationRole
from app.models.organization_member import OrganizationMember

router = APIRouter(prefix="/team", tags=["team"])
team_repository = TeamRepository()
team_service = TeamService()
audit_log_service = AuditLogService()
team_logger = get_logger("events.team")


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
        status=team_service.resolve_member_status(member),
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


@router.get("/members", response_model=TeamMemberListResponse)
async def list_team_members(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TeamMemberListResponse:
    organization_id = _organization_id_from_principal(principal)
    members = await team_repository.list_members(
        db_session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )
    total = await team_repository.count_members(db_session, organization_id=organization_id)
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


@router.post(
    "/members/invite", response_model=InviteTeamMemberResponse, status_code=status.HTTP_201_CREATED
)
async def invite_team_member(
    request: Request,
    payload: InviteTeamMemberRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InviteTeamMemberResponse:
    organization_id = _organization_id_from_principal(principal)
    actor_user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    normalized_email = team_service.normalize_email(payload.email)

    user = await team_repository.get_user_by_email(db_session, email=normalized_email)
    invited = False

    if user is None:
        invited = True
        user = await team_repository.create_user(
            db_session,
            organization_id=organization_id,
            external_auth_id=team_service.invited_external_auth_id(),
            email=normalized_email,
            display_name=team_service.display_name_for_email(normalized_email),
        )

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

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.member.invited",
        resource_type="organization_member",
        resource_id=member.id,
        request_id=request_id,
        metadata={
            "email": normalized_email,
            "role": payload.role,
            "invited": invited,
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await db_session.commit()

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
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
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

    member.role = payload.role
    await db_session.flush()

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_user_id,
        action="team.member.role.updated",
        resource_type="organization_member",
        resource_id=member.id,
        request_id=request_id,
        metadata={
            "role": payload.role,
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


@router.delete("/members/{member_id}", response_model=TeamMemberRemoveResponse)
async def remove_team_member(
    request: Request,
    member_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(OrganizationRole.owner.value, OrganizationRole.admin.value)),
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
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Owner cannot be removed",
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
