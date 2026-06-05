"""SCIM 2.0 endpoints — authenticated via SCIM bearer token (not JWT session)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.params import Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.scim.schemas.scim import (
    SCIM2Email,
    SCIM2ErrorResponse,
    SCIM2ListResponse,
    SCIM2PatchOp,
    SCIM2UserRequest,
    SCIM2UserResponse,
)
from app.domains.scim.services.scim_service import SCIMService
from app.models.org_scim_config import OrgSCIMConfig
from app.models.user import User

router = APIRouter(prefix="/scim/v2", tags=["scim"])

_scim_service = SCIMService()
_audit_service = AuditLogService()

_SCIM_CONTENT_TYPE = "application/scim+json"


def _scim_error(http_status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content=SCIM2ErrorResponse(
            status=str(http_status), detail=detail
        ).model_dump(),
        media_type=_SCIM_CONTENT_TYPE,
    )


def _user_to_scim(user: User, base_url: str) -> SCIM2UserResponse:
    return SCIM2UserResponse(
        id=str(user.id),
        externalId=user.scim_external_id,
        userName=user.email,
        displayName=user.display_name,
        active=user.is_active,
        emails=[SCIM2Email(value=user.email, primary=True, type="work")],
        meta={
            "resourceType": "User",
            "location": f"{base_url}/Users/{user.id}",
        },
    )


def _scim_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/v1/scim/v2"


async def _authenticate(
    authorization: str | None,
    db_session: AsyncSession,
) -> OrgSCIMConfig:
    """Validate SCIM bearer token and return the matching OrgSCIMConfig."""
    token_hash = _scim_service.authenticate_scim_request(authorization)
    if token_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed SCIM bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    config = await _scim_service.get_config_by_token_hash(
        db_session, token_hash=token_hash
    )
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked SCIM bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return config


# ── ServiceProviderConfig ─────────────────────────────────────────────────────

@router.get("/ServiceProviderConfig")
async def service_provider_config() -> JSONResponse:
    payload = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "name": "OAuth Bearer Token",
                "description": "Authentication scheme using the OAuth Bearer Token standard.",
                "specUri": "http://www.rfc-editor.org/info/rfc6750",
                "type": "oauthbearertoken",
                "primary": True,
            }
        ],
    }
    return JSONResponse(content=payload, media_type=_SCIM_CONTENT_TYPE)


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/Users")
async def list_users(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
    startIndex: int = 1,
    count: int = 100,
    filter: str | None = None,  # noqa: A002
) -> JSONResponse:
    config = await _authenticate(authorization, db_session)

    filter_email: str | None = None
    if filter:
        # Support minimal SCIM filter: userName eq "user@example.com"
        import re
        m = re.match(r'userName\s+eq\s+"([^"]+)"', filter, re.IGNORECASE)
        if m:
            filter_email = m.group(1)

    users, total = await _scim_service.list_users(
        db_session,
        organization_id=config.organization_id,
        start_index=startIndex,
        count=count,
        filter_email=filter_email,
    )
    base_url = _scim_base_url(request)
    resources = [_user_to_scim(u, base_url) for u in users]
    response = SCIM2ListResponse(
        totalResults=total,
        startIndex=startIndex,
        itemsPerPage=len(resources),
        Resources=resources,
    )
    return JSONResponse(content=response.model_dump(), media_type=_SCIM_CONTENT_TYPE)


@router.post("/Users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: SCIM2UserRequest,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    config = await _authenticate(authorization, db_session)

    # Resolve email: prefer emails list, fall back to userName
    email = payload.userName
    if payload.emails:
        primary = next((e for e in payload.emails if e.primary), payload.emails[0])
        email = primary.value

    scim_id = payload.externalId or payload.userName
    display_name = payload.displayName
    if display_name is None and payload.name:
        display_name = payload.name.formatted or (
            " ".join(
                filter(None, [payload.name.givenName, payload.name.familyName])
            ) or None
        )

    try:
        user = await _scim_service.provision_user(
            db_session,
            organization_id=config.organization_id,
            scim_external_id=scim_id,
            email=email,
            display_name=display_name,
            is_active=payload.active,
            config=config,
        )
    except Exception as exc:
        await db_session.rollback()
        return _scim_error(status.HTTP_409_CONFLICT, f"Could not provision user: {exc}")

    await _audit_service.record(
        db_session,
        organization_id=config.organization_id,
        user_id=None,
        action="scim.user.provisioned",
        resource_type="user",
        resource_id=user.id,
        request_id=None,
        metadata={"email": user.email, "scim_external_id": scim_id, "severity": "info"},
    )
    await db_session.commit()

    base_url = _scim_base_url(request)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=_user_to_scim(user, base_url).model_dump(),
        media_type=_SCIM_CONTENT_TYPE,
    )


@router.get("/Users/{scim_id}")
async def get_user(
    scim_id: str,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    config = await _authenticate(authorization, db_session)

    user = await _scim_service.get_user_by_scim_id(
        db_session,
        scim_external_id=scim_id,
        organization_id=config.organization_id,
    )
    if user is None:
        return _scim_error(status.HTTP_404_NOT_FOUND, f"User {scim_id!r} not found.")

    base_url = _scim_base_url(request)
    return JSONResponse(
        content=_user_to_scim(user, base_url).model_dump(),
        media_type=_SCIM_CONTENT_TYPE,
    )


@router.put("/Users/{scim_id}")
async def replace_user(
    scim_id: str,
    payload: SCIM2UserRequest,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    config = await _authenticate(authorization, db_session)

    user = await _scim_service.get_user_by_scim_id(
        db_session,
        scim_external_id=scim_id,
        organization_id=config.organization_id,
    )
    if user is None:
        return _scim_error(status.HTTP_404_NOT_FOUND, f"User {scim_id!r} not found.")

    display_name = payload.displayName
    if display_name is None and payload.name:
        display_name = payload.name.formatted

    user = await _scim_service.update_user(
        db_session,
        user=user,
        display_name=display_name,
        is_active=payload.active,
        config=config,
    )
    await _audit_service.record(
        db_session,
        organization_id=config.organization_id,
        user_id=None,
        action="scim.user.updated",
        resource_type="user",
        resource_id=user.id,
        request_id=None,
        metadata={
            "scim_external_id": scim_id,
            "active": payload.active,
            "severity": "info",
        },
    )
    await db_session.commit()

    base_url = _scim_base_url(request)
    return JSONResponse(
        content=_user_to_scim(user, base_url).model_dump(),
        media_type=_SCIM_CONTENT_TYPE,
    )


@router.patch("/Users/{scim_id}")
async def patch_user(
    scim_id: str,
    payload: SCIM2PatchOp,
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Handle SCIM PATCH — supports active toggle and displayName updates."""
    config = await _authenticate(authorization, db_session)

    user = await _scim_service.get_user_by_scim_id(
        db_session,
        scim_external_id=scim_id,
        organization_id=config.organization_id,
    )
    if user is None:
        return _scim_error(status.HTTP_404_NOT_FOUND, f"User {scim_id!r} not found.")

    is_active = user.is_active
    display_name = user.display_name

    for op in payload.Operations:
        op_name = str(op.get("op", "")).lower()
        path = str(op.get("path", "")).lower()
        value = op.get("value")

        if op_name == "replace":
            if path == "active" or path == "":
                if isinstance(value, dict):
                    if "active" in value:
                        is_active = bool(value["active"])
                    if "displayName" in value:
                        display_name = value["displayName"]
                elif path == "active":
                    is_active = bool(value)
            elif path == "displayname":
                display_name = str(value) if value is not None else None

    user = await _scim_service.update_user(
        db_session,
        user=user,
        display_name=display_name,
        is_active=is_active,
        config=config,
    )
    await _audit_service.record(
        db_session,
        organization_id=config.organization_id,
        user_id=None,
        action="scim.user.patched",
        resource_type="user",
        resource_id=user.id,
        request_id=None,
        metadata={
            "scim_external_id": scim_id,
            "active": is_active,
            "severity": "info",
        },
    )
    await db_session.commit()

    base_url = _scim_base_url(request)
    return JSONResponse(
        content=_user_to_scim(user, base_url).model_dump(),
        media_type=_SCIM_CONTENT_TYPE,
    )


@router.delete("/Users/{scim_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    scim_id: str,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """SCIM DELETE — deactivates user and removes org membership."""
    config = await _authenticate(authorization, db_session)

    user = await _scim_service.get_user_by_scim_id(
        db_session,
        scim_external_id=scim_id,
        organization_id=config.organization_id,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {scim_id!r} not found.",
        )

    await _scim_service.deprovision_user(db_session, user=user, config=config)
    await _audit_service.record(
        db_session,
        organization_id=config.organization_id,
        user_id=None,
        action="scim.user.deprovisioned",
        resource_type="user",
        resource_id=user.id,
        request_id=None,
        metadata={
            "scim_external_id": scim_id,
            "email": user.email,
            "severity": "warning",
        },
    )
    await db_session.commit()
