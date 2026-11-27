"""WebSocket chat handshake authentication (R02-10).

Three handshake modes, tried in this order:

1. ``?ticket=`` - a single-use ticket from ``POST /chat/ws-ticket``. An invalid
   ticket fails the handshake; it never falls through to another mode.
2. ``Authorization`` header - for non-browser clients (API keys, service
   accounts, bearer JWTs). Authenticated exactly like an HTTP request, so
   ``X-Organization-Id`` is honoured.
3. ``?token=`` - the legacy access token in the URL. Deprecated; accepted only
   while ``CHAT_WS_ALLOW_QUERY_TOKEN`` is true.

Ticket auth trusts only the ticket's user, organisation and session ids. The
user, the app session and a current membership are reloaded, and the role comes
from that membership, so a role change or removal after issue takes effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Address, Headers

from app.auth.dependencies import authenticate_bearer_request
from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.auth.providers.app_provider import AppAuthProvider
from app.auth.repository import AuthRepository
from app.core.config import settings
from app.core.logging import log_query_event
from app.core.metrics import record_chat_ws_auth
from app.domains.chat.services.ws_ticket_service import WsTicketClaims, WsTicketService

WsAuthMethod = Literal["ticket", "header", "query_token"]

_auth_repository = AuthRepository()
_app_provider = AppAuthProvider()
ws_ticket_service = WsTicketService()


@dataclass(frozen=True)
class WsAuthResult:
    principal: AuthenticatedPrincipal | None
    method: WsAuthMethod | None
    failure: str | None = None


async def _ticket_principal(
    db_session: AsyncSession, claims: WsTicketClaims
) -> tuple[AuthenticatedPrincipal | None, str | None]:
    try:
        user_uuid = UUID(claims.user_id)
        org_uuid = UUID(claims.organization_id)
    except ValueError:
        return None, "ticket_claims_invalid"

    user = await _auth_repository.get_user_by_id(db_session, user_id=user_uuid)
    if user is None:
        return None, "unknown_user"
    if not user.is_active:
        return None, "user_inactive"

    if claims.auth_provider == "app" and claims.auth_session_id:
        try:
            session_record = await _app_provider.load_active_session(
                db_session, session_id=UUID(claims.auth_session_id)
            )
            _app_provider.ensure_session_owner(session_record, user_id=user.id)
        except (ValueError, AuthenticationError):
            return None, "session_revoked"

    membership = await _auth_repository.get_membership(
        db_session, organization_id=org_uuid, user_id=user_uuid
    )
    if membership is None:
        return None, "membership_missing"

    principal = AuthenticatedPrincipal(
        user_id=str(user.id),
        organization_id=str(org_uuid),
        email=user.email,
        roles=[membership.role],
        auth_provider=claims.auth_provider,
        auth_session_id=claims.auth_session_id,
    )
    return principal, None


async def principal_from_ticket(
    db_session: AsyncSession, claims: WsTicketClaims
) -> AuthenticatedPrincipal | None:
    """Rebuild the principal for redeemed ticket claims, or ``None`` when no longer valid."""
    principal, _ = await _ticket_principal(db_session, claims)
    return principal


def _bearer_request(
    headers: Headers, client: Address | None, *, bearer: str | None = None
) -> Request:
    raw_headers = [
        (k, v) for k, v in headers.raw if bearer is None or k.lower() != b"authorization"
    ]
    if bearer is not None:
        raw_headers.append((b"authorization", f"Bearer {bearer}".encode("latin-1")))
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/chat/ws",
        "query_string": b"",
        "headers": raw_headers,
        "client": (client.host, client.port) if client is not None else None,
        "asgi": {"version": "3.0"},
    }
    return Request(scope)


async def _authenticate_request(
    request: Request, db_session: AsyncSession
) -> tuple[AuthenticatedPrincipal | None, str | None]:
    try:
        return await authenticate_bearer_request(request, db_session), None
    except (AuthenticationError, AuthorizationError):
        return None, "invalid_credentials"
    except Exception:
        # Fail closed on anything unexpected (malformed header bytes, provider errors).
        return None, "auth_error"


def _result(
    principal: AuthenticatedPrincipal | None, method: WsAuthMethod | None, failure: str | None
) -> WsAuthResult:
    outcome = "accepted" if principal is not None else "rejected"
    record_chat_ws_auth(method or "none", outcome)
    return WsAuthResult(principal=principal, method=method, failure=failure)


async def authenticate_ws_handshake(
    *,
    headers: Headers,
    client: Address | None,
    ticket: str | None,
    token: str | None,
    db_session: AsyncSession,
) -> WsAuthResult:
    """Authenticate a ``/chat/ws`` handshake; see the module docstring for the order."""
    if ticket is not None:
        claims = await ws_ticket_service.redeem(ticket.strip())
        if claims is None:
            return _result(None, "ticket", "ticket_invalid")
        principal, failure = await _ticket_principal(db_session, claims)
        return _result(principal, "ticket", failure)

    if headers.get("authorization"):
        principal, failure = await _authenticate_request(
            _bearer_request(headers, client), db_session
        )
        return _result(principal, "header", failure)

    raw_token = (token or "").strip()
    if raw_token:
        if not settings.chat_ws_allow_query_token:
            return _result(None, "query_token", "query_token_disabled")
        principal, failure = await _authenticate_request(
            _bearer_request(headers, client, bearer=raw_token), db_session
        )
        if principal is not None:
            log_query_event(
                event="chat.ws.query_token_used",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
            )
        return _result(principal, "query_token", failure)

    return _result(None, None, "missing_credentials")
