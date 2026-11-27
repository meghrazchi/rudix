"""Buffered ``last_used_at`` / ``last_used_ip`` for API keys and service accounts (R04-06).

The request path never writes these columns. It sends one Lua script per request that
keeps the newest touch per credential in a Redis hash (monotonic: an older ``used_at`` never
replaces a newer one) and adds the credential to a dirty set. The beat task
``usage.touch.flush`` pops the dirty set atomically and writes a max-guarded bulk UPDATE.

Keys use the environment as the cluster hash tag (``rudix:{<env>}:usage_touch:...``), so the
pop script can read the per-credential hashes it derives from the dirty set members.

If Redis is missing or fails, the touch is dropped and counted; it never raises and never
falls back to a database write.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from prometheus_client import Counter

from app.clients import redis_client as redis_module
from app.clients.redis_scripts import ScriptStore, as_text, get_script
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import registry

logger = get_logger("auth.usage_touch")


class UsageTouchKind(StrEnum):
    api_key = "api_key"
    service_account_token = "service_account_token"
    service_account = "service_account"


FIELD_USED_AT = "used_at_ms"
FIELD_IP = "ip"

# KEYS[1] = dirty set, KEYS[2..n] = per-credential hashes.
# ARGV[1] = used_at (epoch ms); then for each hash i: ARGV[2i] = ip, ARGV[2i+1] = member.
TOUCH_SCRIPT = """
local used_at = tonumber(ARGV[1])
local updated = 0
for i = 2, #KEYS do
  local current = tonumber(redis.call('HGET', KEYS[i], 'used_at_ms') or '-1')
  if used_at > current then
    redis.call('HSET', KEYS[i], 'used_at_ms', ARGV[1], 'ip', ARGV[2 * (i - 1)])
    updated = updated + 1
  end
  redis.call('SADD', KEYS[1], ARGV[2 * (i - 1) + 1])
end
return updated
"""

# KEYS[1] = dirty set; ARGV[1] = batch size, ARGV[2] = hash key prefix.
# Returns {member1, {field, value, ...}, member2, {...}, ...}.
POP_SCRIPT = """
local members = redis.call('SPOP', KEYS[1], tonumber(ARGV[1]))
local out = {}
for _, member in ipairs(members) do
  local key = ARGV[2] .. member
  table.insert(out, member)
  table.insert(out, redis.call('HGETALL', key))
  redis.call('DEL', key)
end
return out
"""

USAGE_TOUCH_BUFFERED_TOTAL = Counter(
    "rudix_usage_touch_buffered_total",
    "Credential usage touches buffered in Redis",
    ["kind"],
    registry=registry,
)
USAGE_TOUCH_FLUSHED_TOTAL = Counter(
    "rudix_usage_touch_flushed_total",
    "Credential usage touches written to the database by the flush task",
    ["kind"],
    registry=registry,
)
USAGE_TOUCH_DROPPED_TOTAL = Counter(
    "rudix_usage_touch_dropped_total",
    "Credential usage touches dropped because Redis was missing or failed",
    ["kind", "reason"],
    registry=registry,
)


@dataclass(frozen=True)
class UsageTouch:
    kind: UsageTouchKind
    credential_id: UUID
    used_at: datetime
    ip_address: str | None = None

    @property
    def member(self) -> str:
        return f"{self.kind.value}:{self.credential_id}"


def key_prefix() -> str:
    return f"rudix:{{{settings.environment.value}}}:usage_touch:"


def dirty_key() -> str:
    return f"{key_prefix()}dirty"


def _to_ms(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


def _from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def touch_reference_impl(
    store: ScriptStore, keys: Sequence[str], args: Sequence[Any], now_ms: int
) -> int:
    """Python twin of ``TOUCH_SCRIPT``."""
    del now_ms
    used_at = int(args[0])
    updated = 0
    for i in range(1, len(keys)):
        current = int(store.hget(keys[i], FIELD_USED_AT) or -1)
        if used_at > current:
            store.hset(keys[i], {FIELD_USED_AT: str(args[0]), FIELD_IP: str(args[2 * i - 1])})
            updated += 1
        store.sadd(keys[0], str(args[2 * i]))
    return updated


def pop_reference_impl(
    store: ScriptStore, keys: Sequence[str], args: Sequence[Any], now_ms: int
) -> list[Any]:
    """Python twin of ``POP_SCRIPT``."""
    del now_ms
    out: list[Any] = []
    for member in store.spop(keys[0], int(args[0])):
        key = f"{args[1]}{member}"
        flat: list[str] = []
        for field, value in store.hgetall(key).items():
            flat.extend([field, value])
        out.extend([member, flat])
        store.delete(key)
    return out


def _drop(touches: Sequence[UsageTouch], reason: str) -> None:
    for item in touches:
        USAGE_TOUCH_DROPPED_TOTAL.labels(kind=item.kind.value, reason=reason).inc()


async def buffer_touches(
    redis: Any, touches: Sequence[UsageTouch], *, count_buffered: bool = True
) -> None:
    """Buffer touches sharing one ``used_at`` in one round trip. Redis errors propagate."""
    if not touches:
        return
    prefix = key_prefix()
    keys = [dirty_key(), *(f"{prefix}{item.member}" for item in touches)]
    args: list[Any] = [_to_ms(touches[0].used_at)]
    for item in touches:
        args.extend([item.ip_address or "", item.member])
    script = get_script(redis, TOUCH_SCRIPT)
    await script(keys=keys, args=args)
    if not count_buffered:
        return
    for item in touches:
        USAGE_TOUCH_BUFFERED_TOTAL.labels(kind=item.kind.value).inc()


async def record_touches(touches: Sequence[UsageTouch]) -> None:
    """Request-path entry point: buffer or drop, never raise, never touch the database."""
    redis = redis_module.redis_client
    if redis is None:
        _drop(touches, "redis_unavailable")
        return
    try:
        await buffer_touches(redis, touches)
    except Exception as exc:
        _drop(touches, "redis_error")
        logger.warning(
            "usage_touch.dropped",
            kinds=sorted({item.kind.value for item in touches}),
            error=exc.__class__.__name__,
        )


def _parse_member(member: str) -> tuple[UsageTouchKind, UUID] | None:
    kind_text, _, id_text = member.partition(":")
    try:
        return UsageTouchKind(kind_text), UUID(id_text)
    except ValueError:
        return None


def parse_popped(reply: Sequence[Any]) -> list[UsageTouch]:
    """Turn a ``POP_SCRIPT`` reply into touches, skipping malformed members or empty hashes."""
    touches: list[UsageTouch] = []
    for index in range(0, len(reply) - 1, 2):
        parsed = _parse_member(as_text(reply[index]))
        flat = [as_text(v) for v in reply[index + 1]]
        fields = dict(zip(flat[0::2], flat[1::2], strict=True))
        if parsed is None or FIELD_USED_AT not in fields:
            continue
        kind, credential_id = parsed
        touches.append(
            UsageTouch(
                kind=kind,
                credential_id=credential_id,
                used_at=_from_ms(int(fields[FIELD_USED_AT])),
                ip_address=fields.get(FIELD_IP) or None,
            )
        )
    return touches


async def pop_touches(redis: Any, *, batch_size: int) -> list[UsageTouch]:
    script = get_script(redis, POP_SCRIPT)
    reply = await script(keys=[dirty_key()], args=[batch_size, key_prefix()])
    return parse_popped(reply or [])


async def rebuffer_touches(redis: Any, touches: Sequence[UsageTouch]) -> None:
    """Put popped touches back after a failed flush; the monotonic script makes it idempotent."""
    for item in touches:
        await buffer_touches(redis, [item], count_buffered=False)
