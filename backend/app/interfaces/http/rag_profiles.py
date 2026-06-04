from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.rag_profiles.repositories.rag_profiles import RagProfileRepository
from app.domains.rag_profiles.schemas.rag_profiles import (
    CollectionOverrideListResponse,
    CollectionOverrideResponse,
    CreateRagProfileRequest,
    RagProfileListResponse,
    RagProfileResponse,
    RagProfileVersionListResponse,
    RagProfileVersionResponse,
    ResolvedRagProfileResponse,
    RollbackRagProfileRequest,
    SetCollectionOverrideRequest,
    UpdateRagProfileRequest,
)
from app.domains.rag_profiles.services.rag_profile_service import (
    SYSTEM_DEFAULT_CONFIG,
    create_profile_with_version,
    resolve_profile_for_context,
    rollback_to_version,
    update_profile_with_version,
)
from app.models.enums import OrganizationRole
from app.models.rag_profile import RagProfile, RagProfileCollectionOverride, RagProfileVersion

router = APIRouter(prefix="/rag-profiles", tags=["rag-profiles"])

_profile_repo = RagProfileRepository()
_audit_service = AuditLogService()

_ALL_ROLES = (
    OrganizationRole.owner.value,
    OrganizationRole.admin.value,
    OrganizationRole.member.value,
    OrganizationRole.viewer.value,
)
_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _user_id(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid user context",
        ) from exc


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label} not found",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _profile_to_response(profile: RagProfile) -> RagProfileResponse:
    return RagProfileResponse(
        profile_id=str(profile.id),
        organization_id=str(profile.organization_id),
        name=profile.name,
        description=profile.description,
        config=dict(profile.config or {}),
        is_default=profile.is_default,
        is_archived=profile.is_archived,
        version=profile.version,
        created_by_id=str(profile.created_by_id) if profile.created_by_id else None,
        updated_by_id=str(profile.updated_by_id) if profile.updated_by_id else None,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _version_to_response(version: RagProfileVersion) -> RagProfileVersionResponse:
    return RagProfileVersionResponse(
        version_id=str(version.id),
        rag_profile_id=str(version.rag_profile_id),
        version_number=version.version_number,
        config_snapshot=dict(version.config_snapshot or {}),
        change_note=version.change_note,
        changed_by_id=str(version.changed_by_id) if version.changed_by_id else None,
        created_at=version.created_at,
    )


def _override_to_response(
    override: RagProfileCollectionOverride,
) -> CollectionOverrideResponse:
    return CollectionOverrideResponse(
        override_id=str(override.id),
        organization_id=str(override.organization_id),
        collection_id=str(override.collection_id),
        rag_profile_id=str(override.rag_profile_id),
        created_by_id=str(override.created_by_id) if override.created_by_id else None,
        created_at=override.created_at,
    )


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=RagProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_rag_profile(
    request: Request,
    payload: CreateRagProfileRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RagProfileResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)

    config = payload.config.model_dump(exclude_none=True)
    profile = await create_profile_with_version(
        db_session,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        config=config,
        set_as_default=payload.set_as_default,
        created_by_id=user_id,
        change_note=payload.change_note,
    )
    await db_session.commit()
    await db_session.refresh(profile)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="rag_profile.created",
        resource_type="rag_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={"name": profile.name, "is_default": profile.is_default},
    )
    await db_session.commit()

    log_evaluation_event(
        event="rag_profile.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(profile.id),
        status_code=status.HTTP_201_CREATED,
    )
    return _profile_to_response(profile)


@router.get("", response_model=RagProfileListResponse)
async def list_rag_profiles(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ALL_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    include_archived: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RagProfileListResponse:
    organization_id = _org_id(principal)
    profiles = await _profile_repo.list_profiles(
        db_session,
        organization_id=organization_id,
        include_archived=include_archived,
        limit=limit,
        offset=offset,
    )
    total = await _profile_repo.count_profiles(
        db_session,
        organization_id=organization_id,
        include_archived=include_archived,
    )
    return RagProfileListResponse(
        items=[_profile_to_response(p) for p in profiles],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/resolve", response_model=ResolvedRagProfileResponse)
async def resolve_rag_profile(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ALL_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    collection_id: Annotated[str | None, Query()] = None,
) -> ResolvedRagProfileResponse:
    """Return the effective RAG profile for a given context (collection optional)."""
    organization_id = _org_id(principal)
    collection_uuid: UUID | None = None
    if collection_id:
        collection_uuid = _parse_uuid(collection_id, "Collection")

    profile, source = await resolve_profile_for_context(
        db_session,
        organization_id=organization_id,
        collection_id=collection_uuid,
    )

    if profile is None:
        return ResolvedRagProfileResponse(
            profile_id="system",
            name="System Default",
            version=0,
            config=SYSTEM_DEFAULT_CONFIG,
            source="system_default",
        )

    return ResolvedRagProfileResponse(
        profile_id=str(profile.id),
        name=profile.name,
        version=profile.version,
        config=dict(profile.config or {}),
        source=source,  # type: ignore[arg-type]
    )


@router.get("/{profile_id}", response_model=RagProfileResponse)
async def get_rag_profile(
    profile_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ALL_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RagProfileResponse:
    organization_id = _org_id(principal)
    profile_uuid = _parse_uuid(profile_id, "RAG profile")
    profile = await _profile_repo.get_profile(
        db_session, profile_id=profile_uuid, organization_id=organization_id
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RAG profile not found",
        )
    return _profile_to_response(profile)


@router.patch("/{profile_id}", response_model=RagProfileResponse)
async def update_rag_profile(
    profile_id: str,
    request: Request,
    payload: UpdateRagProfileRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RagProfileResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    profile_uuid = _parse_uuid(profile_id, "RAG profile")
    profile = await _profile_repo.get_profile(
        db_session, profile_id=profile_uuid, organization_id=organization_id
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RAG profile not found",
        )
    if profile.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived profiles cannot be edited. Unarchive first.",
        )

    new_config = payload.config.model_dump(exclude_none=True) if payload.config else None
    profile = await update_profile_with_version(
        db_session,
        profile,
        name=payload.name,
        description=payload.description,
        config=new_config,
        set_as_default=payload.set_as_default,
        updated_by_id=user_id,
        change_note=payload.change_note,
        organization_id=organization_id,
    )
    await db_session.commit()
    await db_session.refresh(profile)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="rag_profile.updated",
        resource_type="rag_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={"name": profile.name, "version": profile.version},
    )
    await db_session.commit()
    return _profile_to_response(profile)


@router.post("/{profile_id}/archive", response_model=RagProfileResponse)
async def archive_rag_profile(
    profile_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RagProfileResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    profile_uuid = _parse_uuid(profile_id, "RAG profile")
    profile = await _profile_repo.get_profile(
        db_session, profile_id=profile_uuid, organization_id=organization_id
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RAG profile not found",
        )
    if profile.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RAG profile is already archived",
        )
    if profile.is_default:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot archive the default profile. Assign a new default first.",
        )

    await _profile_repo.update_profile(
        db_session,
        profile,
        is_archived=True,
        updated_by_id=user_id,
    )
    await db_session.commit()
    await db_session.refresh(profile)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="rag_profile.archived",
        resource_type="rag_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={"name": profile.name},
    )
    await db_session.commit()
    return _profile_to_response(profile)


@router.post("/{profile_id}/unarchive", response_model=RagProfileResponse)
async def unarchive_rag_profile(
    profile_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RagProfileResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    profile_uuid = _parse_uuid(profile_id, "RAG profile")
    profile = await _profile_repo.get_profile(
        db_session, profile_id=profile_uuid, organization_id=organization_id
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RAG profile not found",
        )
    if not profile.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RAG profile is not archived",
        )

    await _profile_repo.update_profile(
        db_session,
        profile,
        is_archived=False,
        updated_by_id=user_id,
    )
    await db_session.commit()
    await db_session.refresh(profile)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="rag_profile.unarchived",
        resource_type="rag_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={"name": profile.name},
    )
    await db_session.commit()
    return _profile_to_response(profile)


@router.post("/{profile_id}/set-default", response_model=RagProfileResponse)
async def set_default_rag_profile(
    profile_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RagProfileResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    profile_uuid = _parse_uuid(profile_id, "RAG profile")
    profile = await _profile_repo.get_profile(
        db_session, profile_id=profile_uuid, organization_id=organization_id
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RAG profile not found",
        )
    if profile.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot set an archived profile as default",
        )
    if profile.is_default:
        return _profile_to_response(profile)

    await _profile_repo.clear_default_flag(
        db_session,
        organization_id=organization_id,
        exclude_id=profile_uuid,
    )
    await _profile_repo.update_profile(db_session, profile, is_default=True, updated_by_id=user_id)
    await db_session.commit()
    await db_session.refresh(profile)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="rag_profile.set_default",
        resource_type="rag_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={"name": profile.name},
    )
    await db_session.commit()
    return _profile_to_response(profile)


# ---------------------------------------------------------------------------
# Version history and rollback
# ---------------------------------------------------------------------------


@router.get("/{profile_id}/versions", response_model=RagProfileVersionListResponse)
async def list_rag_profile_versions(
    profile_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ALL_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RagProfileVersionListResponse:
    organization_id = _org_id(principal)
    profile_uuid = _parse_uuid(profile_id, "RAG profile")
    profile = await _profile_repo.get_profile(
        db_session, profile_id=profile_uuid, organization_id=organization_id
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RAG profile not found",
        )
    versions = await _profile_repo.list_versions(
        db_session, rag_profile_id=profile_uuid, organization_id=organization_id
    )
    return RagProfileVersionListResponse(
        items=[_version_to_response(v) for v in versions],
        total=len(versions),
    )


@router.post("/{profile_id}/rollback", response_model=RagProfileResponse)
async def rollback_rag_profile(
    profile_id: str,
    request: Request,
    payload: RollbackRagProfileRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RagProfileResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    profile_uuid = _parse_uuid(profile_id, "RAG profile")
    profile = await _profile_repo.get_profile(
        db_session, profile_id=profile_uuid, organization_id=organization_id
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RAG profile not found",
        )
    if profile.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived profiles cannot be rolled back",
        )

    version = await _profile_repo.get_version(
        db_session,
        rag_profile_id=profile_uuid,
        version_number=payload.version_number,
        organization_id=organization_id,
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {payload.version_number} not found for this profile",
        )
    if payload.version_number == profile.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile is already at the requested version",
        )

    profile = await rollback_to_version(
        db_session,
        profile,
        version,
        rolled_back_by_id=user_id,
        change_note=payload.change_note,
        organization_id=organization_id,
    )
    await db_session.commit()
    await db_session.refresh(profile)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="rag_profile.rolled_back",
        resource_type="rag_profile",
        resource_id=profile.id,
        request_id=request_id,
        metadata={
            "name": profile.name,
            "rolled_back_to": payload.version_number,
            "new_version": profile.version,
        },
    )
    await db_session.commit()
    return _profile_to_response(profile)


# ---------------------------------------------------------------------------
# Collection overrides
# ---------------------------------------------------------------------------


@router.get("/overrides/collections", response_model=CollectionOverrideListResponse)
async def list_collection_overrides(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ALL_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionOverrideListResponse:
    organization_id = _org_id(principal)
    overrides = await _profile_repo.list_collection_overrides(
        db_session, organization_id=organization_id
    )
    return CollectionOverrideListResponse(
        items=[_override_to_response(o) for o in overrides],
        total=len(overrides),
    )


@router.put(
    "/overrides/collections/{collection_id}",
    response_model=CollectionOverrideResponse,
)
async def set_collection_override(
    collection_id: str,
    request: Request,
    payload: SetCollectionOverrideRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CollectionOverrideResponse:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    collection_uuid = _parse_uuid(collection_id, "Collection")
    profile_uuid = _parse_uuid(payload.rag_profile_id, "RAG profile")

    profile = await _profile_repo.get_profile(
        db_session, profile_id=profile_uuid, organization_id=organization_id
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RAG profile not found",
        )
    if profile.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot assign an archived profile to a collection",
        )

    override = await _profile_repo.upsert_collection_override(
        db_session,
        organization_id=organization_id,
        collection_id=collection_uuid,
        rag_profile_id=profile_uuid,
        created_by_id=user_id,
    )
    await db_session.commit()
    await db_session.refresh(override)

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="rag_profile.collection_override.set",
        resource_type="rag_profile_collection_override",
        resource_id=override.id,
        request_id=request_id,
        metadata={
            "collection_id": collection_id,
            "rag_profile_id": payload.rag_profile_id,
        },
    )
    await db_session.commit()
    return _override_to_response(override)


@router.delete(
    "/overrides/collections/{collection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_collection_override(
    collection_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*_ADMIN_ROLES)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _org_id(principal)
    user_id = _user_id(principal)
    request_id = _request_id(request)
    collection_uuid = _parse_uuid(collection_id, "Collection")

    override = await _profile_repo.get_collection_override(
        db_session,
        organization_id=organization_id,
        collection_id=collection_uuid,
    )
    if override is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection override not found",
        )

    override_id = override.id
    await _profile_repo.delete_collection_override(db_session, override)
    await db_session.commit()

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="rag_profile.collection_override.removed",
        resource_type="rag_profile_collection_override",
        resource_id=override_id,
        request_id=request_id,
        metadata={"collection_id": collection_id},
    )
    await db_session.commit()
