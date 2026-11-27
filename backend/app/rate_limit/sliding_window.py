"""Atomic sliding-window rate limit check shared by every limiter (R04-07).

One Lua script per check, so a request costs one Redis round trip. The estimate for a
window of ``W`` ms at ``elapsed`` ms into the current window is::

    estimate = previous * (1 - elapsed / W) + current

The script checks the user counter (and, when ``org_limit > 0``, the organisation counter)
*before* incrementing, so a rejected request is not counted. Only when both allow does it
increment the current-window keys, setting ``PEXPIRE 2 * W`` on a new key so the counter
survives as the next window's "previous".

Keys: the caller passes base keys that already contain a hash tag (``{org:<id>}``) so the
four keys of one check live in one cluster slot; ``:w:<index>`` is appended here. The app
clock picks the window index; the script measures ``elapsed`` with ``redis.call('TIME')``
and clamps it to ``[0, W]``, so app servers with skewed clocks agree on the weighting.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from prometheus_client import Counter

from app.clients.redis_scripts import ScriptStore, as_text, get_script
from app.core.metrics import registry

SLIDING_WINDOW_SCRIPT = """
local user_limit = tonumber(ARGV[1])
local org_limit = tonumber(ARGV[2])
local window_ms = tonumber(ARGV[3])
local window_index = tonumber(ARGV[4])
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local elapsed = now_ms - window_index * window_ms
if elapsed < 0 then elapsed = 0 end
if elapsed > window_ms then elapsed = window_ms end
local weight = 1 - elapsed / window_ms

local function read(curr_key, prev_key)
  local curr = tonumber(redis.call('GET', curr_key) or '0')
  local prev = tonumber(redis.call('GET', prev_key) or '0')
  return curr, prev, prev * weight + curr
end

local function retry_ms(curr, prev, limit)
  if limit <= 0 then return window_ms - elapsed end
  if curr >= limit then
    return math.ceil(window_ms - elapsed + window_ms * (1 - limit / curr))
  end
  return math.max(0, math.ceil(window_ms * (1 - (limit - curr) / prev) - elapsed))
end

local u_curr, u_prev, u_est = read(KEYS[1], KEYS[2])
local remaining = math.floor(user_limit - u_est - 1)
if u_est >= user_limit then
  return {0, 'user', remaining, retry_ms(u_curr, u_prev, user_limit)}
end
if org_limit > 0 then
  local o_curr, o_prev, o_est = read(KEYS[3], KEYS[4])
  if o_est >= org_limit then
    return {0, 'org', remaining, retry_ms(o_curr, o_prev, org_limit)}
  end
  if redis.call('INCR', KEYS[3]) == 1 then redis.call('PEXPIRE', KEYS[3], 2 * window_ms) end
end
if redis.call('INCR', KEYS[1]) == 1 then redis.call('PEXPIRE', KEYS[1], 2 * window_ms) end
return {1, '', remaining, 0}
"""

SCOPE_USER = "user"
SCOPE_ORG = "org"

RATE_LIMIT_ORG_LIMITED_TOTAL = Counter(
    "rudix_rate_limit_org_limited_total",
    "Requests rejected because the organisation aggregate rate limit was reached",
    ["scope"],
    registry=registry,
)


def record_org_limited(scope: str) -> None:
    RATE_LIMIT_ORG_LIMITED_TOTAL.labels(scope=scope).inc()


@dataclass(frozen=True)
class SlidingWindowResult:
    allowed: bool
    scope: str
    remaining: int
    retry_after_ms: int

    @property
    def retry_after_seconds(self) -> int:
        return max(1, math.ceil(self.retry_after_ms / 1000))


def _retry_ms(curr: float, prev: float, limit: int, elapsed: float, window_ms: int) -> int:
    if limit <= 0:
        return int(window_ms - elapsed)
    if curr >= limit:
        return math.ceil(window_ms - elapsed + window_ms * (1 - limit / curr))
    return max(0, math.ceil(window_ms * (1 - (limit - curr) / prev) - elapsed))


def reference_impl(
    store: ScriptStore, keys: Sequence[str], args: Sequence[Any], now_ms: int
) -> list[Any]:
    """Python twin of ``SLIDING_WINDOW_SCRIPT`` (``now_ms`` stands in for Redis ``TIME``)."""
    user_limit, org_limit, window_ms, window_index = (int(a) for a in args[:4])
    elapsed = float(min(max(now_ms - window_index * window_ms, 0), window_ms))
    weight = 1 - elapsed / window_ms

    def read(curr_key: str, prev_key: str) -> tuple[float, float, float]:
        curr = float(store.get(curr_key) or 0)
        prev = float(store.get(prev_key) or 0)
        return curr, prev, prev * weight + curr

    u_curr, u_prev, u_est = read(keys[0], keys[1])
    remaining = math.floor(user_limit - u_est - 1)
    if u_est >= user_limit:
        return [0, SCOPE_USER, remaining, _retry_ms(u_curr, u_prev, user_limit, elapsed, window_ms)]
    if org_limit > 0:
        o_curr, o_prev, o_est = read(keys[2], keys[3])
        if o_est >= org_limit:
            retry = _retry_ms(o_curr, o_prev, org_limit, elapsed, window_ms)
            return [0, SCOPE_ORG, remaining, retry]
        if store.incr(keys[2]) == 1:
            store.pexpire(keys[2], 2 * window_ms)
    if store.incr(keys[0]) == 1:
        store.pexpire(keys[0], 2 * window_ms)
    return [1, "", remaining, 0]


def _app_now_ms() -> int:
    return int(time.time() * 1000)


# Indirection so tests can align the app clock with the fake Redis clock.
now_ms: Callable[[], int] = _app_now_ms


def build_keys(
    *, user_key: str, org_key: str | None, window_ms: int, current_ms: int
) -> tuple[list[str], int]:
    index = current_ms // window_ms
    org_base = org_key if org_key is not None else user_key
    keys = [
        f"{user_key}:w:{index}",
        f"{user_key}:w:{index - 1}",
        f"{org_base}:w:{index}",
        f"{org_base}:w:{index - 1}",
    ]
    return keys, index


async def check(
    redis: Any,
    *,
    user_key: str,
    user_limit: int,
    window_seconds: int,
    org_key: str | None = None,
    org_limit: int = 0,
) -> SlidingWindowResult:
    """Run one sliding-window check (one round trip). ``org_limit <= 0`` disables the org part.

    Redis errors propagate; each limiter maps them to its own open/closed failure mode.
    """
    window_ms = max(1, window_seconds) * 1000
    effective_org_limit = org_limit if org_key is not None and org_limit > 0 else 0
    keys, index = build_keys(
        user_key=user_key, org_key=org_key, window_ms=window_ms, current_ms=now_ms()
    )
    script = get_script(redis, SLIDING_WINDOW_SCRIPT)
    reply = await script(keys=keys, args=[user_limit, effective_org_limit, window_ms, index])
    allowed, scope, remaining, retry_after_ms = reply
    return SlidingWindowResult(
        allowed=int(allowed) == 1,
        scope=as_text(scope),
        remaining=int(remaining),
        retry_after_ms=int(retry_after_ms),
    )
