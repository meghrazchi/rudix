from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.service_accounts.repositories.service_accounts import ServiceAccountsRepository
from app.domains.service_accounts.schemas.service_accounts import (
    CreateServiceAccountRequest,
    CreateServiceAccountTokenRequest,
    ServiceAccountListResponse,
    ServiceAccountResponse,
    ServiceAccountTokenCreatedResponse,
    ServiceAccountTokenListResponse,
    UpdateServiceAccountRequest,
)
from app.domains.service_accounts.services.service_accounts_service import ServiceAccountsService
from app.models.permissions import PermissionType

router = APIRouter(prefix="/admin/service-accounts", tags=["service_accounts"])
_repo = ServiceAccountsRepository()
_service = ServiceAccountsService()
_audit = AuditLogService()
logger = get_logger("events.service_accounts")


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
            detail="Invalid principal context",
        ) from exc


def _request_id(request: Request) -> str | None:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid.strip():
        return rid
    return request.headers.get("x-request-id")


def _parse_uuid(value: str, label: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found"
        ) from exc


# ── Service account CRUD ──────────────────────────────────────────────────────


@router.get("", response_model=ServiceAccountListResponse)
async def list_service_accounts(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_list)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountListResponse:
    org_id = _org_id(principal)
    accounts = await _repo.list_service_accounts(db_session, organization_id=org_id)
    items = [_service.to_service_account_response(a) for a in accounts]
    return ServiceAccountListResponse(items=items, total=len(items))


@router.post("", response_model=ServiceAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_service_account(
    request: Request,
    payload: CreateServiceAccountRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountResponse:
    org_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)

    account = await _repo.create_service_account(
        db_session,
        organization_id=org_id,
        name=payload.name,
        description=payload.description,
        environment=payload.environment,
        scopes=payload.scopes,
        created_by_id=actor_id,
    )
    await _audit.record(
        db_session,
        organization_id=org_id,
        user_id=actor_id,
        action="service_accounts.account.created",
        resource_type="service_account",
        resource_id=account.id,
        request_id=request_id,
        metadata={
            "name": account.name,
            "environment": account.environment,
            "scopes": account.scopes,
        },
    )
    await db_session.commit()

    logger.info(
        "service_accounts.account.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        account_id=str(account.id),
        name=account.name,
    )
    return _service.to_service_account_response(account)


@router.get("/{account_id}", response_model=ServiceAccountResponse)
async def get_service_account(
    account_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_list)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountResponse:
    org_id = _org_id(principal)
    parsed_id = _parse_uuid(account_id, "Service account")
    account = await _repo.get_service_account(
        db_session, account_id=parsed_id, organization_id=org_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service account not found"
        )
    return _service.to_service_account_response(account)


@router.patch("/{account_id}", response_model=ServiceAccountResponse)
async def update_service_account(
    request: Request,
    account_id: str,
    payload: UpdateServiceAccountRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountResponse:
    org_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)
    parsed_id = _parse_uuid(account_id, "Service account")

    account = await _repo.get_service_account(
        db_session, account_id=parsed_id, organization_id=org_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service account not found"
        )

    account = await _repo.update_service_account(
        db_session,
        account=account,
        name=payload.name,
        description=payload.description,
        environment=payload.environment,
    )
    await _audit.record(
        db_session,
        organization_id=org_id,
        user_id=actor_id,
        action="service_accounts.account.updated",
        resource_type="service_account",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": account.name},
    )
    await db_session.commit()
    await db_session.refresh(account)

    logger.info(
        "service_accounts.account.updated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        account_id=account_id,
    )
    return _service.to_service_account_response(account)


@router.post("/{account_id}/deactivate", response_model=ServiceAccountResponse)
async def deactivate_service_account(
    request: Request,
    account_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_revoke)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountResponse:
    org_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)
    parsed_id = _parse_uuid(account_id, "Service account")

    account = await _repo.get_service_account(
        db_session, account_id=parsed_id, organization_id=org_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service account not found"
        )
    if not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Service account is already inactive"
        )

    account = await _repo.deactivate_service_account(db_session, account=account)
    await _audit.record(
        db_session,
        organization_id=org_id,
        user_id=actor_id,
        action="service_accounts.account.deactivated",
        resource_type="service_account",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": account.name},
    )
    await db_session.commit()
    await db_session.refresh(account)

    logger.info(
        "service_accounts.account.deactivated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        account_id=account_id,
    )
    return _service.to_service_account_response(account)


@router.post("/{account_id}/reactivate", response_model=ServiceAccountResponse)
async def reactivate_service_account(
    request: Request,
    account_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_manage)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountResponse:
    org_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)
    parsed_id = _parse_uuid(account_id, "Service account")

    account = await _repo.get_service_account(
        db_session, account_id=parsed_id, organization_id=org_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service account not found"
        )
    if account.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Service account is already active"
        )

    account = await _repo.reactivate_service_account(db_session, account=account)
    await _audit.record(
        db_session,
        organization_id=org_id,
        user_id=actor_id,
        action="service_accounts.account.reactivated",
        resource_type="service_account",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"name": account.name},
    )
    await db_session.commit()
    await db_session.refresh(account)

    logger.info(
        "service_accounts.account.reactivated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        account_id=account_id,
    )
    return _service.to_service_account_response(account)


# ── Token management ──────────────────────────────────────────────────────────


@router.get("/{account_id}/tokens", response_model=ServiceAccountTokenListResponse)
async def list_tokens(
    account_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_list)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountTokenListResponse:
    org_id = _org_id(principal)
    parsed_id = _parse_uuid(account_id, "Service account")

    account = await _repo.get_service_account(
        db_session, account_id=parsed_id, organization_id=org_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service account not found"
        )

    tokens = await _repo.list_tokens(
        db_session, service_account_id=parsed_id, organization_id=org_id
    )
    items = [_service.to_token_response(t) for t in tokens]
    return ServiceAccountTokenListResponse(items=items, total=len(items))


@router.post(
    "/{account_id}/tokens",
    response_model=ServiceAccountTokenCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_token(
    request: Request,
    account_id: str,
    payload: CreateServiceAccountTokenRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountTokenCreatedResponse:
    org_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)
    parsed_id = _parse_uuid(account_id, "Service account")

    account = await _repo.get_service_account(
        db_session, account_id=parsed_id, organization_id=org_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service account not found"
        )
    if not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot issue tokens for an inactive service account",
        )

    raw_token = ServiceAccountsService.generate_raw_token()
    token_hash = ServiceAccountsService.hash_token(raw_token)
    token_prefix = ServiceAccountsService.token_prefix(raw_token)

    token = await _repo.create_token(
        db_session,
        service_account_id=parsed_id,
        organization_id=org_id,
        name=payload.name,
        token_prefix=token_prefix,
        token_hash=token_hash,
        expires_at=payload.expires_at,
        created_by_id=actor_id,
    )
    await _audit.record(
        db_session,
        organization_id=org_id,
        user_id=actor_id,
        action="service_accounts.token.created",
        resource_type="service_account_token",
        resource_id=token.id,
        request_id=request_id,
        metadata={"account_id": account_id, "name": token.name},
    )
    await db_session.commit()

    logger.info(
        "service_accounts.token.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        account_id=account_id,
        token_id=str(token.id),
    )
    return _service.to_token_created_response(token, raw_token)


@router.delete(
    "/{account_id}/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_token(
    request: Request,
    account_id: str,
    token_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_revoke)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    org_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)
    parsed_account_id = _parse_uuid(account_id, "Service account")
    parsed_token_id = _parse_uuid(token_id, "Token")

    account = await _repo.get_service_account(
        db_session, account_id=parsed_account_id, organization_id=org_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service account not found"
        )

    token = await _repo.get_token(
        db_session,
        token_id=parsed_token_id,
        service_account_id=parsed_account_id,
        organization_id=org_id,
    )
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    if token.status == "revoked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Token is already revoked")

    await _repo.revoke_token(db_session, token=token)
    await _audit.record(
        db_session,
        organization_id=org_id,
        user_id=actor_id,
        action="service_accounts.token.revoked",
        resource_type="service_account_token",
        resource_id=parsed_token_id,
        request_id=request_id,
        metadata={"account_id": account_id, "name": token.name},
    )
    await db_session.commit()

    logger.info(
        "service_accounts.token.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        account_id=account_id,
        token_id=token_id,
    )


@router.post(
    "/{account_id}/tokens/{token_id}/rotate",
    response_model=ServiceAccountTokenCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def rotate_token(
    request: Request,
    account_id: str,
    token_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_permission(PermissionType.service_accounts_create)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ServiceAccountTokenCreatedResponse:
    """Revoke the existing token and issue a new one with the same name and expiry."""
    org_id = _org_id(principal)
    actor_id = _user_id(principal)
    request_id = _request_id(request)
    parsed_account_id = _parse_uuid(account_id, "Service account")
    parsed_token_id = _parse_uuid(token_id, "Token")

    account = await _repo.get_service_account(
        db_session, account_id=parsed_account_id, organization_id=org_id
    )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Service account not found"
        )
    if not account.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot rotate tokens for an inactive service account",
        )

    old_token = await _repo.get_token(
        db_session,
        token_id=parsed_token_id,
        service_account_id=parsed_account_id,
        organization_id=org_id,
    )
    if old_token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    if old_token.status == "revoked":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Cannot rotate a revoked token"
        )

    await _repo.revoke_token(db_session, token=old_token)

    raw_token = ServiceAccountsService.generate_raw_token()
    token_hash = ServiceAccountsService.hash_token(raw_token)
    token_prefix = ServiceAccountsService.token_prefix(raw_token)

    new_token = await _repo.create_token(
        db_session,
        service_account_id=parsed_account_id,
        organization_id=org_id,
        name=old_token.name,
        token_prefix=token_prefix,
        token_hash=token_hash,
        expires_at=old_token.expires_at,
        created_by_id=actor_id,
    )
    await _audit.record(
        db_session,
        organization_id=org_id,
        user_id=actor_id,
        action="service_accounts.token.rotated",
        resource_type="service_account_token",
        resource_id=new_token.id,
        request_id=request_id,
        metadata={"account_id": account_id, "old_token_id": token_id, "name": new_token.name},
    )
    await db_session.commit()
    await db_session.refresh(new_token)

    logger.info(
        "service_accounts.token.rotated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        account_id=account_id,
        old_token_id=token_id,
        new_token_id=str(new_token.id),
    )
    return _service.to_token_created_response(new_token, raw_token)
