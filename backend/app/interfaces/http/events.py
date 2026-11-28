"""``GET /events/stream``: per-user realtime invalidation hints over SSE (R07-07).

Thin adapter over ``app/application/realtime/stream_http.py``. ``404`` while
``REALTIME_EVENTS_ENABLED`` is off, ``503 realtime_unavailable`` without a reachable Redis,
``429 realtime_connection_limit`` above ``REALTIME_MAX_CONNECTIONS_PER_USER``. The token is
read from the ``Authorization`` header like every other route; never from the URL.
"""

from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.realtime import stream_http
from app.auth.dependencies import require_roles
from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.error_codes import (
    REALTIME_CONNECTION_LIMIT,
    REALTIME_CONNECTION_LIMIT_MESSAGE,
    REALTIME_UNAVAILABLE,
    REALTIME_UNAVAILABLE_MESSAGE,
)
from app.core.logging import get_logger
from app.core.metrics_realtime import record_realtime_reconnect
from app.db.session import get_db_session
from app.models.enums import OrganizationRole

_logger = get_logger("realtime.http")

router = APIRouter(prefix="/events", tags=["events"])

_STREAM_DESCRIPTION = (
    "Server-Sent Events for the caller's organisation, filtered to the events the caller may "
    "see. Frames: `id: <n>`, `event: <type>`, `data: {type, organization_id, occurred_at, "
    "payload}`, plus `: keep-alive` comments. Types: `document.status`, `documents.changed`, "
    "`notification.created`, `connector.sync`, `agent.run`, `incident`. Payloads carry ids "
    "and statuses only. Send `Last-Event-ID` to replay buffered events after that id. The "
    "stream ends after `REALTIME_STREAM_MAX_SECONDS`; reconnect."
)


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": REALTIME_UNAVAILABLE, "message": REALTIME_UNAVAILABLE_MESSAGE},
    )


@router.get(
    "/stream",
    response_class=StreamingResponse,
    responses={
        200: {"description": _STREAM_DESCRIPTION, "content": {"text/event-stream": {}}},
        404: {"description": "Realtime events are not enabled for this deployment."},
        429: {"description": "Too many open streams for this user (`realtime_connection_limit`)."},
        503: {"description": "Redis is not reachable (`realtime_unavailable`); keep polling."},
    },
)
async def stream_events(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_roles(*(role.value for role in OrganizationRole))),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    # The authentication dependency left a transaction open on the request session (the
    # same session, cached per request). End it now: the dependency only exits after the
    # response, so the pooled connection would otherwise be held for the whole stream.
    await db_session.commit()
    if not settings.realtime_events_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "feature_not_available",
                "message": "Realtime events are not enabled for this deployment.",
            },
        )
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    organization_id = str(principal.organization_id)
    user_id = str(principal.user_id)
    redis = redis_module.redis_client
    if redis is None:
        raise _unavailable()
    lease_id = uuid4().hex
    try:
        acquired = await stream_http.acquire_connection_slot(
            redis, organization_id=organization_id, user_id=user_id, lease_id=lease_id
        )
    except Exception as exc:
        _logger.warning(
            "realtime.stream.unavailable",
            organization_id=organization_id,
            error=exc.__class__.__name__,
        )
        raise _unavailable() from exc
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": REALTIME_CONNECTION_LIMIT,
                "message": REALTIME_CONNECTION_LIMIT_MESSAGE,
            },
        )
    raw_last_id = request.headers.get("last-event-id")
    if raw_last_id is not None:
        record_realtime_reconnect()
    reader = stream_http.RealtimeStreamReader(
        organization_id=organization_id,
        user_id=user_id,
        roles=principal.roles,
        last_event_id=stream_http.parse_last_event_id(raw_last_id),
        redis=redis,
        lease_id=lease_id,
    )
    _logger.info(
        "realtime.stream.opened",
        organization_id=organization_id,
        user_id=user_id,
        last_event_id=reader.floor,
    )
    return stream_http.stream_response(reader)
