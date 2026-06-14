from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.bots.repositories.bots import BotRepository
from app.domains.bots.schemas.bots import (
    BotCredentialResponse,
    BotCredentialUpdateRequest,
    BotInstallationCreateRequest,
    BotInstallationListResponse,
    BotInstallationResponse,
    BotInstallationUpdateRequest,
    BotSlackOAuthCallbackResponse,
    BotSlackOAuthStartRequest,
    BotSlackOAuthStartResponse,
    BotUserMappingListResponse,
    BotUserMappingResponse,
    BotUserMappingUpsertRequest,
)
from app.domains.bots.services.adapters import (
    BotAskEvent,
    BotTransportAdapter,
    SlackBotAdapter,
    TeamsBotAdapter,
)
from app.domains.bots.services.bot_service import BotAskService
from app.domains.bots.services.credential_vault import BotCredentialVault
from app.domains.bots.services.delivery import BotDeliveryResult, BotDeliveryService
from app.domains.bots.services.oauth import BotOAuthError, BotSlackOAuthService
from app.domains.chat.schemas.chat import SourceScopeRequest
from app.models.bot import BotInstallation, BotUserMapping
from app.models.enums import OrganizationRole
from app.models.organization_member import OrganizationMember
from app.models.user import User

admin_router = APIRouter(prefix="/admin/bots", tags=["bots"])
public_router = APIRouter(prefix="/bots", tags=["bots"])

_ADMIN_ROLES = (OrganizationRole.owner.value, OrganizationRole.admin.value)
_repository = BotRepository()
_ask_service = BotAskService(repository=_repository)
_audit_service = AuditLogService()
_credential_vault = BotCredentialVault()
_delivery_service = BotDeliveryService(credential_vault=_credential_vault)
_slack_oauth_service = BotSlackOAuthService(
    repository=_repository,
    credential_vault=_credential_vault,
    audit_service=_audit_service,
)


def _organization_id(principal: AuthenticatedPrincipal) -> UUID:
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
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


def _normalize_optional_external_id(value: str | None) -> str:
    return (value or "").strip()


def _source_scope_payload(source_scope: SourceScopeRequest | None) -> dict:
    return source_scope.model_dump(mode="json") if source_scope is not None else {}


def _source_scope_response(raw_scope: dict) -> SourceScopeRequest | None:
    if not raw_scope:
        return None
    return SourceScopeRequest.model_validate(raw_scope)


def _installation_response(installation: BotInstallation) -> BotInstallationResponse:
    return BotInstallationResponse(
        id=str(installation.id),
        organization_id=str(installation.organization_id),
        provider=installation.provider,  # type: ignore[arg-type]
        external_workspace_id=installation.external_workspace_id,
        external_tenant_id=installation.external_tenant_id or None,
        external_team_id=installation.external_team_id or None,
        display_name=installation.display_name,
        status=installation.status,  # type: ignore[arg-type]
        default_source_scope=_source_scope_response(installation.default_source_scope_json),
        config=installation.config_json,
        credential=_credential_vault.metadata(installation),
        created_at=installation.created_at,
        updated_at=installation.updated_at,
    )


def _mapping_response(mapping: BotUserMapping) -> BotUserMappingResponse:
    return BotUserMappingResponse(
        id=str(mapping.id),
        installation_id=str(mapping.installation_id),
        organization_id=str(mapping.organization_id),
        rudix_user_id=str(mapping.rudix_user_id),
        external_user_id=mapping.external_user_id,
        external_email=mapping.external_email,
        status=mapping.status,  # type: ignore[arg-type]
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


async def _ensure_user_in_organization(
    session: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
) -> None:
    result = await session.execute(
        select(User.id)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .where(
            User.id == user_id,
            User.organization_id == organization_id,
            User.is_active.is_(True),
            OrganizationMember.organization_id == organization_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rudix user not found in this organization",
        )


async def _require_installation(
    session: AsyncSession,
    *,
    installation_id: str,
    organization_id: UUID,
) -> BotInstallation:
    try:
        parsed_id = UUID(installation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found"
        ) from exc
    installation = await _repository.get_installation(
        session,
        installation_id=parsed_id,
        organization_id=organization_id,
    )
    if installation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found")
    return installation


@admin_router.get("/installations", response_model=BotInstallationListResponse)
async def list_bot_installations(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BotInstallationListResponse:
    organization_id = _organization_id(principal)
    installations = await _repository.list_installations(
        db_session,
        organization_id=organization_id,
    )
    items = [_installation_response(installation) for installation in installations]
    return BotInstallationListResponse(items=items, total=len(items))


@admin_router.post("/slack/oauth/start", response_model=BotSlackOAuthStartResponse)
async def begin_slack_oauth_install(
    request: Request,
    payload: BotSlackOAuthStartRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BotSlackOAuthStartResponse:
    organization_id = _organization_id(principal)
    actor_id = _user_id(principal)
    try:
        result = await _slack_oauth_service.begin_install(
            db_session,
            organization_id=organization_id,
            user_id=actor_id,
            request_id=_request_id(request),
            scopes=payload.scopes,
            redirect_uri=payload.redirect_uri,
        )
    except BotOAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db_session.commit()
    return BotSlackOAuthStartResponse(
        authorization_url=result.authorization_url,
        state=result.state,
        redirect_uri=result.redirect_uri,
        scopes=result.scopes,
        expires_in_seconds=result.expires_in_seconds,
    )


@admin_router.post(
    "/installations",
    response_model=BotInstallationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bot_installation(
    request: Request,
    payload: BotInstallationCreateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BotInstallationResponse:
    organization_id = _organization_id(principal)
    actor_id = _user_id(principal)
    external_tenant_id = _normalize_optional_external_id(payload.external_tenant_id)
    external_team_id = _normalize_optional_external_id(payload.external_team_id)

    existing = await _repository.get_installation_by_external_scope(
        db_session,
        provider=payload.provider,
        external_workspace_id=payload.external_workspace_id,
        external_tenant_id=external_tenant_id,
        external_team_id=external_team_id,
    )
    if existing is not None and existing.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bot workspace is already connected to another organization",
        )

    if existing is None:
        installation = await _repository.create_installation(
            db_session,
            organization_id=organization_id,
            provider=payload.provider,
            external_workspace_id=payload.external_workspace_id,
            external_tenant_id=external_tenant_id,
            external_team_id=external_team_id,
            display_name=payload.display_name,
            status=payload.status,
            default_source_scope=_source_scope_payload(payload.default_source_scope),
            config=payload.config,
            installed_by_user_id=actor_id,
        )
        audit_action = "bots.installation.created"
    else:
        installation = await _repository.update_installation(
            db_session,
            installation=existing,
            display_name=payload.display_name,
            status=payload.status,
            default_source_scope=_source_scope_payload(payload.default_source_scope),
            config=payload.config,
        )
        audit_action = "bots.installation.updated"

    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action=audit_action,
        resource_type="bot_installation",
        resource_id=installation.id,
        request_id=_request_id(request),
        metadata={
            "provider": installation.provider,
            "external_workspace_id": installation.external_workspace_id,
            "external_tenant_id": installation.external_tenant_id,
            "external_team_id": installation.external_team_id,
            "status": installation.status,
        },
    )
    await db_session.commit()
    await db_session.refresh(installation)
    return _installation_response(installation)


@admin_router.patch("/installations/{installation_id}", response_model=BotInstallationResponse)
async def update_bot_installation(
    request: Request,
    installation_id: str,
    payload: BotInstallationUpdateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BotInstallationResponse:
    organization_id = _organization_id(principal)
    actor_id = _user_id(principal)
    try:
        parsed_id = UUID(installation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found"
        ) from exc

    installation = await _repository.get_installation(
        db_session,
        installation_id=parsed_id,
        organization_id=organization_id,
    )
    if installation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found")

    default_scope = None
    if "default_source_scope" in payload.model_fields_set:
        default_scope = _source_scope_payload(payload.default_source_scope)
    installation = await _repository.update_installation(
        db_session,
        installation=installation,
        display_name=payload.display_name,
        status=payload.status,
        default_source_scope=default_scope,
        config=payload.config,
    )
    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="bots.installation.updated",
        resource_type="bot_installation",
        resource_id=installation.id,
        request_id=_request_id(request),
        metadata={
            "provider": installation.provider,
            "external_workspace_id": installation.external_workspace_id,
            "status": installation.status,
        },
    )
    await db_session.commit()
    await db_session.refresh(installation)
    return _installation_response(installation)


@admin_router.put(
    "/installations/{installation_id}/credential",
    response_model=BotCredentialResponse,
)
async def update_bot_installation_credential(
    request: Request,
    installation_id: str,
    payload: BotCredentialUpdateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BotCredentialResponse:
    organization_id = _organization_id(principal)
    actor_id = _user_id(principal)
    installation = await _require_installation(
        db_session,
        installation_id=installation_id,
        organization_id=organization_id,
    )
    installation = await _credential_vault.store_bot_token(
        db_session,
        installation=installation,
        bot_token=payload.bot_token.get_secret_value(),
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="bots.credential.updated",
        resource_type="bot_installation",
        resource_id=installation.id,
        request_id=_request_id(request),
        metadata={
            "provider": installation.provider,
            "external_workspace_id": installation.external_workspace_id,
            "credential_fingerprint": installation.bot_token_fingerprint,
            "scopes": list(installation.bot_token_scopes_json or []),
        },
    )
    await db_session.commit()
    await db_session.refresh(installation)
    return _credential_vault.metadata(installation)


@admin_router.delete(
    "/installations/{installation_id}/credential",
    response_model=BotCredentialResponse,
)
async def clear_bot_installation_credential(
    request: Request,
    installation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BotCredentialResponse:
    organization_id = _organization_id(principal)
    actor_id = _user_id(principal)
    installation = await _require_installation(
        db_session,
        installation_id=installation_id,
        organization_id=organization_id,
    )
    installation = await _credential_vault.clear_bot_token(
        db_session,
        installation=installation,
    )
    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="bots.credential.cleared",
        resource_type="bot_installation",
        resource_id=installation.id,
        request_id=_request_id(request),
        metadata={
            "provider": installation.provider,
            "external_workspace_id": installation.external_workspace_id,
        },
    )
    await db_session.commit()
    await db_session.refresh(installation)
    return _credential_vault.metadata(installation)


@admin_router.get(
    "/installations/{installation_id}/mappings",
    response_model=BotUserMappingListResponse,
)
async def list_bot_user_mappings(
    installation_id: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BotUserMappingListResponse:
    organization_id = _organization_id(principal)
    try:
        parsed_id = UUID(installation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found"
        ) from exc
    installation = await _repository.get_installation(
        db_session,
        installation_id=parsed_id,
        organization_id=organization_id,
    )
    if installation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found")
    mappings = await _repository.list_user_mappings(
        db_session,
        installation_id=installation.id,
        organization_id=organization_id,
    )
    items = [_mapping_response(mapping) for mapping in mappings]
    return BotUserMappingListResponse(items=items, total=len(items))


@admin_router.put(
    "/installations/{installation_id}/mappings",
    response_model=BotUserMappingResponse,
)
async def upsert_bot_user_mapping(
    request: Request,
    installation_id: str,
    payload: BotUserMappingUpsertRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_roles(*_ADMIN_ROLES))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> BotUserMappingResponse:
    organization_id = _organization_id(principal)
    actor_id = _user_id(principal)
    try:
        parsed_installation_id = UUID(installation_id)
        parsed_user_id = UUID(payload.rudix_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mapping target not found"
        ) from exc

    installation = await _repository.get_installation(
        db_session,
        installation_id=parsed_installation_id,
        organization_id=organization_id,
    )
    if installation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Installation not found")

    await _ensure_user_in_organization(
        db_session,
        organization_id=organization_id,
        user_id=parsed_user_id,
    )
    mapping = await _repository.upsert_user_mapping(
        db_session,
        installation_id=installation.id,
        organization_id=organization_id,
        external_user_id=payload.external_user_id,
        rudix_user_id=parsed_user_id,
        external_email=payload.external_email,
        status=payload.status,
        created_by_user_id=actor_id,
    )
    await _audit_service.record(
        db_session,
        organization_id=organization_id,
        user_id=actor_id,
        action="bots.user_mapping.upserted",
        resource_type="bot_installation",
        resource_id=installation.id,
        request_id=_request_id(request),
        metadata={
            "provider": installation.provider,
            "external_workspace_id": installation.external_workspace_id,
            "external_user_id": payload.external_user_id,
            "rudix_user_id": str(parsed_user_id),
            "mapping_status": mapping.status,
        },
    )
    await db_session.commit()
    await db_session.refresh(mapping)
    return _mapping_response(mapping)


async def _handle_event(
    request: Request,
    db_session: AsyncSession,
    *,
    background_tasks: BackgroundTasks,
    adapter: BotTransportAdapter,
) -> JSONResponse:
    raw_body = await request.body()
    adapter.verify_request(request, raw_body)
    parsed = await adapter.parse_event(request, raw_body)
    if isinstance(parsed, dict):
        return JSONResponse(parsed)

    _validate_event(parsed)
    if not _should_process_async(request):
        response = await _ask_service.handle_ask_event(
            db_session,
            event=parsed,
            request_id=_request_id(request),
        )
        return JSONResponse(response.model_dump(mode="json"))

    background_tasks.add_task(
        _process_and_deliver_event,
        db_session,
        parsed,
        _request_id(request),
    )
    return JSONResponse(_ack_payload(parsed))


def _should_process_async(request: Request) -> bool:
    sync_header = request.headers.get("x-rudix-bot-sync", "").strip().lower()
    if sync_header in {"1", "true", "yes"}:
        return False
    async_header = request.headers.get("x-rudix-bot-async", "").strip().lower()
    if async_header in {"1", "true", "yes"}:
        return True
    return settings.bot_process_events_async


def _ack_payload(event: BotAskEvent) -> dict[str, object]:
    loading_text = "Rudix is searching the permitted sources for an answer."
    if event.provider == "slack":
        if event.response_url:
            return {
                "response_type": "ephemeral",
                "text": loading_text,
                "ok": True,
            }
        return {"ok": True}
    if event.provider == "teams":
        return {"ok": True, "text": loading_text}
    return {"ok": True}


async def _process_and_deliver_event(
    db_session: AsyncSession,
    event: BotAskEvent,
    request_id: str | None,
) -> None:
    response = await _ask_service.handle_ask_event(
        db_session,
        event=event,
        request_id=request_id,
    )
    installation = await _ask_service.resolve_installation(db_session, event=event)
    delivery = await _delivery_service.deliver_response(
        installation=installation,
        event=event,
        response=response,
    )
    await _record_delivery_result(
        db_session,
        installation=installation,
        event=event,
        response=response,
        delivery=delivery,
        request_id=request_id,
    )
    await db_session.commit()


async def _record_delivery_result(
    session: AsyncSession,
    *,
    installation: BotInstallation | None,
    event: BotAskEvent,
    response: object,
    delivery: BotDeliveryResult,
    request_id: str | None,
) -> None:
    if installation is None:
        return
    await _audit_service.record(
        session,
        organization_id=installation.organization_id,
        user_id=None,
        action="bots.delivery.completed" if delivery.delivered else "bots.delivery.failed",
        resource_type="bot_installation",
        resource_id=installation.id,
        request_id=request_id,
        metadata={
            "provider": event.provider,
            "external_workspace_id": event.external_workspace_id,
            "external_user_id": event.external_user_id,
            "channel_id": event.channel_id,
            "thread_id": event.thread_id,
            "target": delivery.target,
            "delivered": delivery.delivered,
            "status_code": delivery.status_code,
            "error_code": delivery.error_code,
            "response_ok": getattr(response, "ok", None),
        },
    )


def _validate_event(event: BotAskEvent) -> None:
    if not event.external_workspace_id or not event.external_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_bot_event",
                "message": "Bot event is missing workspace or user identity.",
            },
        )


@public_router.get("/slack/oauth/callback", response_model=BotSlackOAuthCallbackResponse)
async def handle_slack_oauth_callback(
    request: Request,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> BotSlackOAuthCallbackResponse:
    if not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth state")
    try:
        result = await _slack_oauth_service.complete_install(
            db_session,
            state=state,
            code=code,
            error=error,
            request_id=_request_id(request),
        )
    except BotOAuthError as exc:
        await db_session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db_session.commit()
    await db_session.refresh(result.installation)
    return BotSlackOAuthCallbackResponse(
        ok=True,
        installation=_installation_response(result.installation),
        credential=_credential_vault.metadata(result.installation),
    )


@public_router.post("/slack/events")
async def handle_slack_event(
    request: Request,
    background_tasks: BackgroundTasks,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    return await _handle_event(
        request,
        db_session,
        background_tasks=background_tasks,
        adapter=SlackBotAdapter(),
    )


@public_router.post("/teams/events")
async def handle_teams_event(
    request: Request,
    background_tasks: BackgroundTasks,
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> JSONResponse:
    return await _handle_event(
        request,
        db_session,
        background_tasks=background_tasks,
        adapter=TeamsBotAdapter(),
    )
