"""``GET /events/stream``: the per-user realtime event stream (R07-07).

The endpoint has already authenticated the caller, resolved the organisation, and taken one
of the user's connection slots (``acquire_connection_slot``). The reader then:

1. subscribes to the organisation channel first, so nothing published during the replay is
   lost;
2. replays the buffer after ``Last-Event-ID`` (a ``Last-Event-ID`` above the current
   sequence means Redis lost the counter, and the whole buffer is replayed);
3. follows the channel, skipping ids it has already sent.

Every entry is checked again before it is written: its ``organization_id`` must equal the
caller's organisation (the channel name alone is never trusted) and its audience must match
the caller's user id or a role held at connect time. A ``: keep-alive`` comment is written
after ``REALTIME_STREAM_KEEPALIVE_SECONDS`` of silence. The stream ends after
``REALTIME_STREAM_MAX_SECONDS`` so role changes, removed memberships, and token expiry apply
on the client's reconnect. Frames use the 0.5.0 framing of
``app/application/chat/transports/sse.py``; data is the envelope without the audience.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Iterable
from typing import Any

from starlette.responses import StreamingResponse

import app.core.metrics_infra  # noqa: F401 - registers the 0.8.0 gauges for /metrics
from app.application.chat.transports.sse import (
    SSE_HEADERS,
    SSE_KEEPALIVE_FRAME,
    SSE_MEDIA_TYPE,
    format_sse_event,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_realtime import (
    realtime_connection_closed,
    realtime_connection_opened,
    record_realtime_delivered,
)
from app.domains.realtime.events import (
    BufferedEvent,
    buffer_key,
    channel_name,
    connection_key,
    decode_entry,
    sequence_key,
)
from app.rate_limit import concurrency

logger = get_logger("realtime.stream")

_SLOT_TTL_MARGIN_SECONDS = 60
_MAX_POLL_SECONDS = 1.0


async def acquire_connection_slot(
    redis: Any, *, organization_id: str, user_id: str, lease_id: str
) -> bool:
    """Hold one of the user's stream slots as lease ``lease_id``; ``False`` above the cap.

    One atomic script (the semaphore of ``app/rate_limit/concurrency.py``): expired leases
    are purged, then the lease is added only while fewer than the cap remain. Each lease
    expires a minute after the longest stream, so a process that died without releasing it
    frees that slot on its own; a refused attempt never extends anyone's lease. Redis
    errors propagate (the endpoint answers ``503``).
    """
    return await concurrency.try_acquire(
        redis,
        key=connection_key(organization_id, user_id),
        lease_id=lease_id,
        limit=settings.realtime_max_connections_per_user,
        lease_ms=(settings.realtime_stream_max_seconds + _SLOT_TTL_MARGIN_SECONDS) * 1000,
    )


async def release_connection_slot(
    redis: Any, *, organization_id: str, user_id: str, lease_id: str
) -> None:
    try:
        await redis.zrem(connection_key(organization_id, user_id), lease_id)
    except Exception as exc:
        logger.warning(
            "realtime.stream.release_failed",
            organization_id=organization_id,
            error=exc.__class__.__name__,
        )


def parse_last_event_id(raw: str | None) -> int:
    if raw is None:
        return 0
    try:
        return max(0, int(raw.strip()))
    except ValueError:
        return 0


class RealtimeStreamReader:
    def __init__(
        self,
        *,
        organization_id: str,
        user_id: str,
        roles: Iterable[str],
        last_event_id: int,
        redis: Any,
        lease_id: str = "",
    ) -> None:
        self.organization_id = organization_id
        self.user_id = user_id
        self.lease_id = lease_id
        self.roles = frozenset(role.strip().lower() for role in roles if role.strip())
        self.floor = max(0, last_event_id)
        self.redis = redis
        self.delivered = 0
        self._seen: set[int] = set()
        self._order: deque[int] = deque()
        self._seen_cap = max(1, settings.realtime_buffer_max_events) * 2

    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    def _remember(self, event_id: int) -> None:
        self._seen.add(event_id)
        self._order.append(event_id)
        while len(self._order) > self._seen_cap:
            self._seen.discard(self._order.popleft())

    def _allowed(self, item: BufferedEvent) -> bool:
        if item.event.organization_id != self.organization_id:
            return False  # never trust the channel name alone
        return item.event.audience.matches(user_id=self.user_id, roles=self.roles)

    def accept(self, raw: Any) -> str | None:
        """The frame for one buffer or channel entry, or ``None`` when it is not for us."""
        item = decode_entry(raw)
        if item is None or item.id <= self.floor or item.id in self._seen:
            return None
        self._remember(item.id)
        if not self._allowed(item):
            return None
        self.delivered += 1
        record_realtime_delivered(item.event.type)
        data = json.dumps(item.event.envelope(), separators=(",", ":"))
        return format_sse_event(item.id, item.event.type, data)

    async def _reset_floor_if_counter_lost(self) -> None:
        if self.floor == 0:
            return
        current = await self.redis.get(sequence_key(self.organization_id))
        if current is None or int(current) < self.floor:
            self.floor = 0

    async def frames(self) -> AsyncIterator[str]:
        realtime_connection_opened()
        pubsub = self.redis.pubsub()
        try:
            await pubsub.subscribe(channel_name(self.organization_id))
            await self._reset_floor_if_counter_lost()
            for raw in await self.redis.lrange(buffer_key(self.organization_id), 0, -1):
                frame = self.accept(raw)
                if frame is not None:
                    yield frame
            async for frame in self._follow(pubsub):
                yield frame
        except Exception as exc:
            # The client reconnects with Last-Event-ID; a broken Redis answers 503 then.
            logger.warning(
                "realtime.stream.redis_failed",
                organization_id=self.organization_id,
                error=exc.__class__.__name__,
            )
        finally:
            await _close_pubsub(pubsub)
            await release_connection_slot(
                self.redis,
                organization_id=self.organization_id,
                user_id=self.user_id,
                lease_id=self.lease_id,
            )
            realtime_connection_closed()
            logger.info(
                "realtime.stream.closed",
                organization_id=self.organization_id,
                user_id=self.user_id,
                delivered=self.delivered,
            )

    async def _follow(self, pubsub: Any) -> AsyncIterator[str]:
        keepalive = float(settings.realtime_stream_keepalive_seconds)
        poll = min(_MAX_POLL_SECONDS, keepalive)
        deadline = self._now() + settings.realtime_stream_max_seconds
        last_write = self._now()
        while self._now() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=poll)
            if message is not None:
                frame = self.accept(message.get("data"))
                if frame is not None:
                    last_write = self._now()
                    yield frame
                continue
            if self._now() - last_write >= keepalive:
                last_write = self._now()
                yield SSE_KEEPALIVE_FRAME


async def _close_pubsub(pubsub: Any) -> None:
    for method in ("unsubscribe", "aclose"):
        call = getattr(pubsub, method, None)
        if call is None:
            continue
        try:
            await call()
        except Exception:
            pass


def stream_response(reader: RealtimeStreamReader) -> StreamingResponse:
    return StreamingResponse(reader.frames(), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)
