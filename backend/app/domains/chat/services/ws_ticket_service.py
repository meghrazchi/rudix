"""Single-use WebSocket chat handshake tickets (R02-10).

A browser cannot set an ``Authorization`` header on a WebSocket handshake, so it
used to put the access token in ``?token=``, where uvicorn and proxies log it.
Instead the browser asks ``POST /chat/ws-ticket`` for a short-lived ticket and
opens ``/chat/ws?ticket=...``.

Only ``sha256(ticket)`` is used as the Redis key; the raw ticket is never stored
or logged. Redemption uses ``GETDEL`` so a ticket works exactly once.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.logging import get_logger

_KEY_PREFIX = "rudix:ws_ticket:v1:"
_MAX_TICKET_LENGTH = 128
_TICKET_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

logger = get_logger("chat.ws_ticket")


class WsTicketUnavailableError(Exception):
    """Raised when a ticket cannot be issued because Redis is missing or failing."""


class WsTicketClaims(BaseModel):
    user_id: str
    organization_id: str
    auth_provider: str
    auth_session_id: str | None = None
    issued_at: float


def _default_redis() -> Any:
    return redis_module.redis_client


def _ticket_key(ticket: str) -> str:
    return _KEY_PREFIX + hashlib.sha256(ticket.encode()).hexdigest()


def is_well_formed_ticket(ticket: str) -> bool:
    return 0 < len(ticket) <= _MAX_TICKET_LENGTH and bool(_TICKET_PATTERN.match(ticket))


class WsTicketService:
    def __init__(
        self,
        redis_getter: Callable[[], Any] = _default_redis,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._redis_getter = redis_getter
        self._clock = clock

    @staticmethod
    def ttl_seconds() -> int:
        return int(settings.chat_ws_ticket_ttl_seconds)

    async def issue(self, principal: AuthenticatedPrincipal) -> tuple[str, int]:
        """Return ``(ticket, ttl_seconds)`` bound to the principal's user, org and session."""
        if principal.organization_id is None:
            raise WsTicketUnavailableError("principal has no organization")
        redis = self._redis_getter()
        if redis is None:
            raise WsTicketUnavailableError("redis unavailable")
        ttl = self.ttl_seconds()
        claims = WsTicketClaims(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            auth_provider=principal.auth_provider,
            auth_session_id=principal.auth_session_id,
            issued_at=self._clock(),
        )
        ticket = secrets.token_urlsafe(32)
        try:
            stored = await redis.set(_ticket_key(ticket), claims.model_dump_json(), ex=ttl, nx=True)
        except Exception as exc:
            logger.warning("chat.ws.ticket.store_failed", error=exc.__class__.__name__)
            raise WsTicketUnavailableError("redis error") from exc
        if not stored:
            # A 256-bit collision is not realistic; treat it as a store failure.
            raise WsTicketUnavailableError("ticket not stored")
        return ticket, ttl

    async def redeem(self, ticket: str) -> WsTicketClaims | None:
        """Consume the ticket. Returns its claims once; ``None`` when invalid, used or expired."""
        if not is_well_formed_ticket(ticket):
            return None
        redis = self._redis_getter()
        if redis is None:
            return None
        try:
            raw = await redis.getdel(_ticket_key(ticket))
        except Exception as exc:
            logger.warning("chat.ws.ticket.redeem_failed", error=exc.__class__.__name__)
            return None
        if raw is None:
            return None
        try:
            data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            claims = WsTicketClaims.model_validate(data)
        except (ValueError, ValidationError):
            return None
        if self._clock() - claims.issued_at > self.ttl_seconds():
            return None
        return claims
