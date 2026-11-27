"""Sliding-window limiter (R04-07): reference math, round trips, org aggregate, converted limiters."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

# Settings are built at first import; pin the test environment like the other suites.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.config import Environment, RateLimitRedisFailureMode, settings
from app.domains.bots.services.rate_limit import (
    BotRateLimitExceededError,
    BotRateLimitService,
    BotRateLimitUnavailableError,
)
from app.interfaces.http import auth as auth_api
from app.interfaces.http import public_contact
from app.mcp.rate_limit import (
    MCPRateLimiterUnavailableError,
    MCPRateLimitExceededError,
    enforce_mcp_rate_limit,
)
from app.rate_limit import dependencies as rate_limit_dependencies
from app.rate_limit import sliding_window
from app.rate_limit.counter import (
    RateLimitDecision,
    RateLimitedBy,
    RateLimitScope,
    consume_rate_limit,
)
from tests.redis_fakes import BrokenRedis, FakeClock, FakeRedis, align_app_clock

WINDOW_MS = 60_000
# A window start far from zero so "previous window" keys are real indices.
T0 = 29_000_000 * WINDOW_MS


def _args(user_limit: int, org_limit: int, now_ms: int) -> list[int]:
    return [user_limit, org_limit, WINDOW_MS, now_ms // WINDOW_MS]


def _keys(now_ms: int, *, org: bool = True) -> list[str]:
    keys, _ = sliding_window.build_keys(
        user_key="rl:{org:o}:user",
        org_key="rl:{org:o}:org" if org else None,
        window_ms=WINDOW_MS,
        current_ms=now_ms,
    )
    return keys


def _run(fake: FakeRedis, user_limit: int, org_limit: int = 0) -> list[object]:
    now = fake.clock()
    return sliding_window.reference_impl(
        fake.keyspace, _keys(now), _args(user_limit, org_limit, now), now
    )


def _principal(user_id: str, organization_id: str | None = "org-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id, organization_id=organization_id, roles=["member"], auth_provider="test"
    )


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake_clock = FakeClock(T0 + 500)
    align_app_clock(monkeypatch, fake_clock)
    return fake_clock


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> FakeRedis:
    redis = FakeRedis(clock=clock)
    monkeypatch.setattr(redis_module, "redis_client", redis)
    return redis


@pytest.fixture(autouse=True)
def _limits_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "environment", Environment.test)
    monkeypatch.setattr(settings, "rate_limit_disable_in_test", False)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_org_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_org_limit_multiplier", 10)
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.open)


# ── Reference implementation math ────────────────────────────────────────────


def test_fixed_count_within_one_window_and_retry_until_next_window() -> None:
    clock = FakeClock(T0)
    fake = FakeRedis(clock=clock)
    results = [_run(fake, 5) for _ in range(6)]
    assert [r[0] for r in results] == [1, 1, 1, 1, 1, 0]
    assert [r[2] for r in results] == [4, 3, 2, 1, 0, -1]
    assert results[5][1] == "user"
    # curr == limit at elapsed 0: allowed again just after the boundary.
    assert results[5][3] == WINDOW_MS


def test_previous_window_is_weighted_by_remaining_fraction() -> None:
    clock = FakeClock(T0)
    fake = FakeRedis(clock=clock)
    for _ in range(5):
        _run(fake, 5)
    clock.advance(WINDOW_MS + 30_000)  # half-way into the next window: weight 0.5
    results = [_run(fake, 5) for _ in range(4)]
    # estimate = 2.5 + curr: allowed for curr 0, 1, 2; limited at 3 (5.5 > 5).
    assert [r[0] for r in results] == [1, 1, 1, 0]
    # retry when 5 * (1 - f) + 3 < 5, i.e. f > 0.6 -> 36 s into the window, 6 s from now.
    assert results[3][3] == 6_000
    clock.advance(6_001)
    assert _run(fake, 5)[0] == 1


def test_window_boundaries_two_windows_later_forget_everything() -> None:
    clock = FakeClock(T0 + WINDOW_MS - 1)
    fake = FakeRedis(clock=clock)
    for _ in range(3):
        _run(fake, 3)
    assert _run(fake, 3)[0] == 0
    clock.advance(1)  # first ms of the next window: previous weighted at 1.0
    assert _run(fake, 3)[0] == 0
    clock.advance(WINDOW_MS)  # two windows later, previous key is empty
    assert _run(fake, 3)[0] == 1


def test_over_limit_current_window_retry_includes_decay_of_next_window() -> None:
    clock = FakeClock(T0)
    fake = FakeRedis(clock=clock)
    keys = _keys(T0)
    fake.keyspace.set(keys[0], "10")  # e.g. limit lowered after traffic
    result = _run(fake, 5)
    # Next window: 10 * (1 - f) < 5 needs f > 0.5.
    assert result[0] == 0 and result[3] == WINDOW_MS + 30_000


def test_zero_limit_is_always_limited() -> None:
    fake = FakeRedis(clock=FakeClock(T0 + 10_000))
    result = _run(fake, 0)
    assert result[0] == 0 and result[3] == 50_000


def test_elapsed_is_clamped_when_clocks_disagree() -> None:
    clock = FakeClock(T0)
    fake = FakeRedis(clock=clock)
    keys = _keys(T0)
    fake.keyspace.set(keys[1], "4")
    # Redis clock behind the app window start: elapsed clamps to 0, weight 1.
    result = sliding_window.reference_impl(fake.keyspace, keys, _args(4, 0, T0), T0 - 5_000)
    assert result[0] == 0
    # Redis clock a full window ahead: elapsed clamps to W, previous weighted 0.
    result = sliding_window.reference_impl(fake.keyspace, keys, _args(4, 0, T0), T0 + 2 * WINDOW_MS)
    assert result[0] == 1


def test_new_current_key_expires_after_two_windows() -> None:
    fake = FakeRedis(clock=FakeClock(T0))
    _run(fake, 5, org_limit=50)
    keys = _keys(T0)
    assert fake.keyspace.pttl(keys[0]) == 2 * WINDOW_MS
    assert fake.keyspace.pttl(keys[2]) == 2 * WINDOW_MS


def test_org_check_runs_before_any_increment() -> None:
    fake = FakeRedis(clock=FakeClock(T0))
    keys = _keys(T0)
    fake.keyspace.set(keys[2], "3")
    result = _run(fake, 5, org_limit=3)
    assert result[:2] == [0, "org"]
    assert fake.keyspace.get(keys[0]) is None
    assert fake.keyspace.get(keys[2]) == "3"


def test_keys_share_one_hash_tag() -> None:
    keys = _keys(T0)
    assert all("{org:o}" in key for key in keys)
    assert keys[0].endswith(f":w:{T0 // WINDOW_MS}")
    assert keys[1].endswith(f":w:{T0 // WINDOW_MS - 1}")
    assert _keys(T0, org=False)[2] == keys[0]


def test_result_retry_after_seconds_rounds_up_with_minimum_one() -> None:
    result = sliding_window.SlidingWindowResult(False, "user", 0, 1)
    assert result.retry_after_seconds == 1
    assert sliding_window.SlidingWindowResult(False, "user", 0, 59_001).retry_after_seconds == 60


# ── check(): one round trip, script cached per client ───────────────────────


async def test_check_is_one_round_trip_and_registers_script_once(fake: FakeRedis) -> None:
    for expected in range(1, 4):
        result = await sliding_window.check(
            fake, user_key="rl:{org:x}:u", user_limit=10, window_seconds=60
        )
        assert result.allowed
        assert fake.round_trips == expected
    assert fake.commands == ["EVALSHA"] * 3
    assert len(fake.registered_scripts) == 1


async def test_check_decodes_bytes_replies() -> None:
    class BytesRedis:
        def register_script(self, source: str) -> object:
            async def run(keys: list[str], args: list[object]) -> list[object]:
                return [0, b"org", -1, 1500]

            return run

    result = await sliding_window.check(
        BytesRedis(), user_key="k", user_limit=1, window_seconds=60, org_key="o", org_limit=2
    )
    assert result == sliding_window.SlidingWindowResult(False, "org", -1, 1500)
    assert result.retry_after_seconds == 2


async def test_consume_rate_limit_is_one_round_trip(fake: FakeRedis) -> None:
    await consume_rate_limit(scope=RateLimitScope.chat, endpoint="/x", principal=_principal("a"))
    await consume_rate_limit(scope=RateLimitScope.chat, endpoint="/x", principal=_principal("a"))
    assert fake.round_trips == 2
    assert all(
        key.startswith("rate_limit:v2:{org:org-1}:chat:/x:") for key in fake.keyspace.strings
    )


# ── Organisation aggregate ──────────────────────────────────────────────────


def _org_metric(scope: str) -> float:
    return sliding_window.RATE_LIMIT_ORG_LIMITED_TOTAL.labels(scope=scope)._value.get()


async def test_org_limit_trips_for_user_b_after_a_and_b_together_exceed_it(
    fake: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_chat_requests", 3)
    monkeypatch.setattr(settings, "rate_limit_org_limit_multiplier", 1)  # org limit 3
    before = _org_metric("chat")

    async def consume(user: str) -> object:
        return await consume_rate_limit(
            scope=RateLimitScope.chat, endpoint="/chat", principal=_principal(user)
        )

    assert [(await consume("a")).decision for _ in range(2)] == [RateLimitDecision.allowed] * 2
    assert (await consume("b")).decision == RateLimitDecision.allowed
    limited = await consume("b")
    assert limited.decision == RateLimitDecision.limited
    assert limited.limited_by == RateLimitedBy.organization
    assert limited.remaining == 1  # user B is still under its own limit
    assert limited.retry_after_seconds == 60
    assert _org_metric("chat") == before + 1
    # Another organisation is unaffected.
    other = await consume_rate_limit(
        scope=RateLimitScope.chat, endpoint="/chat", principal=_principal("c", "org-2")
    )
    assert other.decision == RateLimitDecision.allowed


async def test_org_limit_sets_scope_header_on_http_429(
    fake: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_upload_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_org_limit_multiplier", 1)
    scope = {"type": "http", "method": "POST", "path": "/u", "headers": [], "route": None}
    request = Request({**scope, "route": SimpleNamespace(path="/u")})
    await rate_limit_dependencies._consume(RateLimitScope.upload, request, _principal("a"))
    with pytest.raises(HTTPException) as org_exc:
        await rate_limit_dependencies._consume(RateLimitScope.upload, request, _principal("b"))
    assert org_exc.value.headers is not None
    assert org_exc.value.headers["X-RateLimit-Scope"] == "organization"
    monkeypatch.setattr(settings, "rate_limit_org_enabled", False)
    with pytest.raises(HTTPException) as user_exc:
        await rate_limit_dependencies._consume(RateLimitScope.upload, request, _principal("a"))
    assert user_exc.value.headers is not None
    assert user_exc.value.headers["X-RateLimit-Scope"] == "user"


async def test_org_limit_disabled_allows_aggregate(
    fake: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_chat_requests", 2)
    monkeypatch.setattr(settings, "rate_limit_org_limit_multiplier", 1)
    monkeypatch.setattr(settings, "rate_limit_org_enabled", False)
    decisions = [
        (
            await consume_rate_limit(
                scope=RateLimitScope.chat, endpoint="/chat", principal=_principal(user)
            )
        ).decision
        for user in ("a", "a", "b", "b", "c")
    ]
    assert decisions == [RateLimitDecision.allowed] * 5
    assert not any(key.endswith(":org:w:" + str(T0 // WINDOW_MS)) for key in fake.keyspace.strings)


async def test_principal_without_organization_has_no_org_limit(
    fake: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_chat_requests", 1)
    monkeypatch.setattr(settings, "rate_limit_org_limit_multiplier", 1)
    for user in ("a", "b", "c"):
        outcome = await consume_rate_limit(
            scope=RateLimitScope.chat, endpoint="/chat", principal=_principal(user, None)
        )
        assert outcome.decision == RateLimitDecision.allowed


# ── Failure modes ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (RateLimitRedisFailureMode.open, RateLimitDecision.allowed),
        (RateLimitRedisFailureMode.closed, RateLimitDecision.unavailable),
    ],
)
@pytest.mark.parametrize("redis", [None, BrokenRedis()])
async def test_consume_failure_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: RateLimitRedisFailureMode,
    expected: RateLimitDecision,
    redis: object,
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", redis)
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", mode)
    outcome = await consume_rate_limit(
        scope=RateLimitScope.chat, endpoint="/chat", principal=_principal("a")
    )
    assert outcome.decision == expected


# ── Converted limiters keep their limits ───────────────────────────────────


async def test_auth_limiter_enforces_limit(fake: FakeRedis) -> None:
    for _ in range(2):
        await auth_api._enforce_auth_rate_limit(action="login", key_parts=["ip", "h"], limit=2)
    with pytest.raises(HTTPException) as exc_info:
        await auth_api._enforce_auth_rate_limit(action="login", key_parts=["ip", "h"], limit=2)
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "60"}
    assert fake.round_trips == 3
    # A different identity has its own counter.
    await auth_api._enforce_auth_rate_limit(action="login", key_parts=["ip", "other"], limit=2)


async def test_auth_limiter_closed_mode_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.closed)
    with pytest.raises(HTTPException) as exc_info:
        await auth_api._enforce_auth_rate_limit(action="login", key_parts=["x"], limit=2)
    assert exc_info.value.status_code == 503


def _contact_request(ip: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/contact",
            "headers": [(b"x-forwarded-for", ip.encode())],
            "client": (ip, 1234),
        }
    )


async def test_contact_limiter_enforces_limit(
    fake: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_contact_requests", 2)
    for _ in range(2):
        await public_contact._enforce_public_contact_rate_limit(_contact_request("10.0.0.1"))
    with pytest.raises(HTTPException) as exc_info:
        await public_contact._enforce_public_contact_rate_limit(_contact_request("10.0.0.1"))
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers is not None
    assert exc_info.value.headers["Retry-After"] == "60"
    assert exc_info.value.headers["X-RateLimit-Remaining"] == "0"
    await public_contact._enforce_public_contact_rate_limit(_contact_request("10.0.0.2"))


@pytest.mark.parametrize(
    ("mode", "status"),
    [(RateLimitRedisFailureMode.closed, 503), (RateLimitRedisFailureMode.open, None)],
)
async def test_contact_limiter_failure_modes(
    monkeypatch: pytest.MonkeyPatch, mode: RateLimitRedisFailureMode, status: int | None
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", mode)
    if status is None:
        await public_contact._enforce_public_contact_rate_limit(_contact_request("10.0.0.1"))
        return
    with pytest.raises(HTTPException) as exc_info:
        await public_contact._enforce_public_contact_rate_limit(_contact_request("10.0.0.1"))
    assert exc_info.value.status_code == status


async def test_mcp_limiter_enforces_limit(fake: FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mcp_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "mcp_rate_limit_requests", 2)
    monkeypatch.setattr(settings, "mcp_rate_limit_window_seconds", 60)
    principal = _principal("a")
    for _ in range(2):
        await enforce_mcp_rate_limit(principal=principal, tool_name="search")
    with pytest.raises(MCPRateLimitExceededError) as exc_info:
        await enforce_mcp_rate_limit(principal=principal, tool_name="search")
    assert exc_info.value.retry_after_seconds == 60
    assert exc_info.value.limit == 2
    assert exc_info.value.remaining == -1
    await enforce_mcp_rate_limit(principal=principal, tool_name="other")


@pytest.mark.parametrize("closed", [True, False])
async def test_mcp_limiter_failure_modes(monkeypatch: pytest.MonkeyPatch, closed: bool) -> None:
    monkeypatch.setattr(settings, "mcp_rate_limit_enabled", True)
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    mode = RateLimitRedisFailureMode.closed if closed else RateLimitRedisFailureMode.open
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", mode)
    if closed:
        with pytest.raises(MCPRateLimiterUnavailableError):
            await enforce_mcp_rate_limit(principal=_principal("a"), tool_name="search")
    else:
        await enforce_mcp_rate_limit(principal=_principal("a"), tool_name="search")


async def test_bot_limiter_enforces_limit(fake: FakeRedis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_bot_requests", 2)
    service = BotRateLimitService()
    kwargs = {"provider": "slack", "external_workspace_id": "T1", "external_user_id": "U1"}
    for _ in range(2):
        await service.consume(**kwargs)
    with pytest.raises(BotRateLimitExceededError) as exc_info:
        await service.consume(**kwargs)
    assert exc_info.value.retry_after_seconds == 60
    await service.consume(**{**kwargs, "external_user_id": "U2"})


@pytest.mark.parametrize("closed", [True, False])
async def test_bot_limiter_failure_modes(monkeypatch: pytest.MonkeyPatch, closed: bool) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    mode = RateLimitRedisFailureMode.closed if closed else RateLimitRedisFailureMode.open
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", mode)
    service = BotRateLimitService()
    kwargs = {"provider": "slack", "external_workspace_id": "T1", "external_user_id": "U1"}
    if closed:
        with pytest.raises(BotRateLimitUnavailableError):
            await service.consume(**kwargs)
    else:
        await service.consume(**kwargs)
