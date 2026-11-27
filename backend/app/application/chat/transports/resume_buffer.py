"""Resume buffer of a WebSocket chat run (R05-13, plan contract 4.2.7).

``BufferingEmitter`` is the ``WsEmitter`` of a run when Redis is configured: before each
event goes to the socket it is appended (as the event JSON) to a Redis list

    rudix:{env}:chat:resume:v1:{organization_id}:{user_id}:{message_id}

kept for ``CHAT_RESUME_BUFFER_TTL_SECONDS`` after the last write. The key contains the
organisation and the user of the principal that started the run; ``chat.resume`` builds it
from its own principal, so another user or organisation can never read it. Past
``CHAT_RESUME_BUFFER_MAX_EVENTS`` entries, a ``generation.delta`` is merged into the last
entry when that entry is a delta too: the entry keeps the newest ``stream_sequence`` and a
private ``coalesced`` list of ``[stream_sequence, length]`` segments, so a reader can cut
the text a client already has. Other events are always appended.

``replay_buffer`` sends the buffered events with a ``stream_sequence`` above the client's
last one, then tails the list every ``CHAT_RESUME_POLL_MS`` until a terminal event
(``chat.completed``, ``chat.error``, ``chat.cancelled``). While it tails it refreshes the
``:attached`` marker, which keeps a dropped run alive past its grace window, and
``request_cancel`` sets the ``:cancel`` marker that the run's grace watcher honours.

A failing Redis never fails the run: the buffer stops writing (counted in
``rudix_chat_resume_buffer_errors_total``) and the run continues unbuffered.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.application.chat.transports.ws import WebSocketLike, WsEmitter, WsSequence, ws_send
from app.clients.redis_scripts import ScriptStore, get_script
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import CHAT_RESUME_BUFFER_ERRORS_TOTAL
from app.domains.chat.schemas.chat_ws import ChatWSOutboundEvent

logger = get_logger("chat.resume")

TERMINAL_EVENTS = frozenset({"chat.completed", "chat.error", "chat.cancelled"})
_DELTA = "generation.delta"
_COALESCED = "coalesced"
# The attached marker outlives a few polls, so a live reader keeps it set.
_ATTACHED_TTL_SECONDS = 5

APPEND_SCRIPT = """
if ARGV[1] == 'set' and redis.call('EXISTS', KEYS[1]) == 1 then
  redis.call('LSET', KEYS[1], -1, ARGV[2])
else
  redis.call('RPUSH', KEYS[1], ARGV[2])
end
redis.call('PEXPIRE', KEYS[1], tonumber(ARGV[3]))
return redis.call('LLEN', KEYS[1])
"""


def append_reference_impl(
    store: ScriptStore, keys: Sequence[str], args: Sequence[Any], now_ms: int
) -> int:
    """Python twin of ``APPEND_SCRIPT``."""
    del now_ms
    key = keys[0]
    mode, value, ttl_ms = str(args[0]), str(args[1]), int(args[2])
    if mode == "set" and store.exists(key):
        store.lset(key, -1, value)
    else:
        store.rpush(key, value)
    store.pexpire(key, ttl_ms)
    return store.llen(key)


def resume_key(organization_id: UUID | str, user_id: UUID | str, message_id: UUID | str) -> str:
    env = settings.environment.value
    return f"rudix:{env}:chat:resume:v1:{organization_id}:{user_id}:{message_id}"


def attached_key(key: str) -> str:
    return f"{key}:attached"


def cancel_key(key: str) -> str:
    return f"{key}:cancel"


def coalesce(previous: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """``previous`` (a delta entry) and ``delta`` as one entry with its segments."""
    previous_text = str((previous.get("payload") or {}).get("text", ""))
    delta_text = str((delta.get("payload") or {}).get("text", ""))
    segments = list(previous.get(_COALESCED) or [])
    if not segments:
        segments = [[int(previous.get("stream_sequence") or 0), len(previous_text)]]
    segments.append([int(delta.get("stream_sequence") or 0), len(delta_text)])
    merged = dict(delta)
    merged["payload"] = {"text": previous_text + delta_text}
    merged[_COALESCED] = segments
    return merged


def trim_entry(entry: dict[str, Any], last_stream_sequence: int) -> dict[str, Any] | None:
    """The part of a stored entry the client does not have yet (``None`` when it has all)."""
    if int(entry.get("stream_sequence") or 0) <= last_stream_sequence:
        return None
    event = dict(entry)
    segments = event.pop(_COALESCED, None)
    if segments:
        seen = sum(int(length) for seq, length in segments if int(seq) <= last_stream_sequence)
        text = str((event.get("payload") or {}).get("text", ""))
        event["payload"] = {"text": text[seen:]}
    return event


class ResumeBuffer:
    """Writer of one run's buffer (the run is its only writer)."""

    def __init__(self, redis: Any, key: str) -> None:
        self._redis = redis
        self.key = key
        self.count = 0
        self.failed = False
        self._last_delta: dict[str, Any] | None = None

    async def append(self, outbound: ChatWSOutboundEvent) -> None:
        if self.failed:
            return
        entry: dict[str, Any] = json.loads(outbound.to_json())
        mode = "push"
        if (
            outbound.event == _DELTA
            and self._last_delta is not None
            and self.count >= settings.chat_resume_buffer_max_events
        ):
            entry = coalesce(self._last_delta, entry)
            mode = "set"
        try:
            script = get_script(self._redis, APPEND_SCRIPT)
            length = await script(
                keys=[self.key],
                args=[mode, json.dumps(entry), settings.chat_resume_buffer_ttl_seconds * 1000],
            )
        except Exception as exc:
            self.failed = True
            CHAT_RESUME_BUFFER_ERRORS_TOTAL.inc()
            logger.warning("chat.resume.buffer_failed", error=exc.__class__.__name__)
            return
        self.count = int(length)
        self._last_delta = entry if outbound.event == _DELTA else None


class BufferingEmitter(WsEmitter):
    """``WsEmitter`` that writes every event to the resume buffer before sending it."""

    def __init__(self, websocket: WebSocketLike, *, buffer: ResumeBuffer, **kwargs: Any) -> None:
        super().__init__(websocket, stream_sequences=True, **kwargs)
        self.buffer = buffer

    async def _deliver(self, outbound: ChatWSOutboundEvent) -> None:
        await self.buffer.append(outbound)
        await ws_send(self._websocket, outbound)

    async def buffer_cancelled(self) -> None:
        """Record ``chat.cancelled`` as the run's terminal event (buffer only: the
        connection that cancelled sends its own ``chat.cancelled``)."""
        await self.buffer.append(self._outbound("chat.cancelled", None))


@dataclass
class ReplayResult:
    found: bool  # the buffer existed when the resume started
    replayed: int = 0
    terminal: str | None = None
    expired: bool = False  # the buffer vanished before a terminal event


SendText = Callable[[str], Awaitable[None]]


def _decode(raw: Any) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, dict) else None


class _Replayer:
    def __init__(self, redis: Any, key: str, last: int, sequence: WsSequence) -> None:
        self.redis = redis
        self.key = key
        self.last = last
        self.sequence = sequence
        self.position = 0  # entries read so far
        self.terminal: str | None = None

    async def read(self) -> list[dict[str, Any]] | None:
        """New events since the previous read; ``None`` when the list is gone. The last
        entry read is read again because a coalesced delta may have grown."""
        start = max(0, self.position - 1)
        raw = await self.redis.lrange(self.key, start, -1)
        if not raw and self.position > 0:
            return None
        self.position = start + len(raw)
        events: list[dict[str, Any]] = []
        for item in raw:
            entry = _decode(item)
            if entry is None:
                continue
            event = trim_entry(entry, self.last)
            if event is None:
                continue
            self.last = int(event.get("stream_sequence") or self.last)
            event["sequence"] = 0  # renumbered on this connection when sent
            events.append(event)
            if event.get("event") in TERMINAL_EVENTS:
                self.terminal = str(event["event"])
                break
        return events

    async def send(self, send_text: SendText, events: list[dict[str, Any]]) -> None:
        for event in events:
            event["sequence"] = self.sequence.next()
            await send_text(json.dumps(event))


async def replay_buffer(
    redis: Any,
    key: str,
    *,
    last_stream_sequence: int,
    sequence: WsSequence,
    send_text: SendText,
    on_resumed: Callable[[int], Awaitable[None]],
) -> ReplayResult:
    """Replay and tail the buffer (see the module docstring). ``on_resumed(replayed)`` is
    awaited before the first replayed event. Redis errors propagate."""
    replayer = _Replayer(redis, key, last_stream_sequence, sequence)
    if not await redis.exists(key):
        return ReplayResult(found=False)
    first = await replayer.read() or []
    await redis.set(attached_key(key), "1", ex=_ATTACHED_TTL_SECONDS)
    await on_resumed(len(first))
    await replayer.send(send_text, first)
    result = ReplayResult(found=True, replayed=len(first))
    poll_seconds = settings.chat_resume_poll_ms / 1000
    deadline = asyncio.get_running_loop().time() + settings.chat_resume_buffer_ttl_seconds
    last_attach = asyncio.get_running_loop().time()
    while replayer.terminal is None:
        if asyncio.get_running_loop().time() >= deadline:
            result.expired = True
            break
        await asyncio.sleep(poll_seconds)
        now = asyncio.get_running_loop().time()
        if now - last_attach >= 1.0:
            await redis.set(attached_key(key), "1", ex=_ATTACHED_TTL_SECONDS)
            last_attach = now
        events = await replayer.read()
        if events is None:
            result.expired = True
            break
        await replayer.send(send_text, events)
    result.terminal = replayer.terminal
    return result


async def request_cancel(redis: Any, key: str) -> None:
    """Ask the run behind ``key`` (on any replica) to cancel; errors are logged only."""
    try:
        await redis.set(cancel_key(key), "1", ex=settings.chat_resume_buffer_ttl_seconds)
    except Exception as exc:
        logger.warning("chat.resume.cancel_failed", error=exc.__class__.__name__)


async def read_flag(redis: Any, key: str) -> bool:
    """Whether a marker key is set; a failing Redis reads as unset."""
    try:
        return bool(await redis.get(key))
    except Exception:
        return False
