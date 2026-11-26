"""``POST /chat/ws-ticket``: single-use handshake tickets for ``/chat/ws`` (R02-10)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.application.chat.ws_auth import ws_ticket_service
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.core.logging import log_query_event
from app.domains.chat.schemas.chat_ws import ChatWsTicketResponse
from app.domains.chat.services.ws_ticket_service import WsTicketUnavailableError
from app.models.enums import OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/ws-ticket", response_model=ChatWsTicketResponse)
async def create_chat_ws_ticket(
    response: Response,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
) -> ChatWsTicketResponse:
    response.headers["Cache-Control"] = "no-store"
    if not settings.feature_chat_websocket_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "chat_websocket_disabled"},
            headers={"Cache-Control": "no-store"},
        )
    try:
        ticket, ttl = await ws_ticket_service.issue(principal)
    except WsTicketUnavailableError as exc:
        log_query_event(
            event="chat.ws.ticket.unavailable",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ws_ticket_unavailable"},
            headers={"Cache-Control": "no-store"},
        ) from exc
    log_query_event(
        event="chat.ws.ticket.issued",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        ttl_seconds=ttl,
    )
    return ChatWsTicketResponse(ticket=ticket, expires_in=ttl)
