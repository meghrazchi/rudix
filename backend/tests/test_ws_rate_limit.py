from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import WebSocketDisconnect

from app.application.chat.ws_auth import WsAuthResult
from app.auth.models import AuthenticatedPrincipal
from app.clients import redis_client as redis_module
from app.core.config import RateLimitRedisFailureMode, settings
from app.interfaces.http import chat as chat_api
from app.rate_limit.counter import (
    RateLimitDecision,
    RateLimitScope,
    consume_rate_limit,
)
from tests.redis_fakes import BrokenRedis, FakeClock, FakeRedis, align_app_clock


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-1",
        organization_id="org-1",
        roles=["member"],
        auth_provider="test",
    )


@pytest.fixture(autouse=True)
def _enable_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_disable_in_test", False)
    monkeypatch.setattr(settings, "rate_limit_disable_in_development", False)
    monkeypatch.setattr(settings, "rate_limit_chat_requests", 2)


_WINDOW_START_MS = 29_000_000 * 60_000


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    # 30 s into the window: a fresh limit hit retries after the remaining 30 s.
    clock = FakeClock(_WINDOW_START_MS + 30_000)
    align_app_clock(monkeypatch, clock)
    return FakeRedis(clock=clock)


def _set_mode(monkeypatch: pytest.MonkeyPatch, mode: RateLimitRedisFailureMode) -> None:
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", mode)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (RateLimitRedisFailureMode.open, RateLimitDecision.allowed),
        (RateLimitRedisFailureMode.closed, RateLimitDecision.unavailable),
    ],
)
async def test_redis_none(
    monkeypatch: pytest.MonkeyPatch, mode: RateLimitRedisFailureMode, expected: RateLimitDecision
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    _set_mode(monkeypatch, mode)
    outcome = await consume_rate_limit(
        scope=RateLimitScope.chat, endpoint="/chat/ws", principal=_principal()
    )
    assert outcome.decision == expected


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (RateLimitRedisFailureMode.open, RateLimitDecision.allowed),
        (RateLimitRedisFailureMode.closed, RateLimitDecision.unavailable),
    ],
)
async def test_redis_error(
    monkeypatch: pytest.MonkeyPatch, mode: RateLimitRedisFailureMode, expected: RateLimitDecision
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", BrokenRedis())
    _set_mode(monkeypatch, mode)
    outcome = await consume_rate_limit(
        scope=RateLimitScope.chat, endpoint="/chat/ws", principal=_principal()
    )
    assert outcome.decision == expected


async def test_limited_after_limit(monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis) -> None:
    monkeypatch.setattr(redis_module, "redis_client", fake_redis)
    decisions = [
        (
            await consume_rate_limit(
                scope=RateLimitScope.chat, endpoint="/chat/ws", principal=_principal()
            )
        )
        for _ in range(3)
    ]
    assert [d.decision for d in decisions] == [
        RateLimitDecision.allowed,
        RateLimitDecision.allowed,
        RateLimitDecision.limited,
    ]
    assert decisions[2].retry_after_seconds == 30
    assert decisions[2].remaining == -1


async def test_disabled_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(redis_module, "redis_client", None)
    _set_mode(monkeypatch, RateLimitRedisFailureMode.closed)
    outcome = await consume_rate_limit(
        scope=RateLimitScope.chat, endpoint="/chat/ws", principal=_principal()
    )
    assert outcome.decision == RateLimitDecision.allowed


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._incoming = [json.dumps({"command": "chat.start", "payload": {"question": "hi"}})]
        self.closed = False
        self.headers: dict[str, str] = {}
        self.client = None

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def receive_text(self) -> str:
        if self._incoming:
            return self._incoming.pop(0)
        await asyncio.sleep(0.01)
        raise WebSocketDisconnect()


async def _run_ws(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeWebSocket, list[int]]:
    calls: list[int] = []

    async def fake_auth(**kwargs: Any) -> WsAuthResult:
        return WsAuthResult(principal=_principal(), method="query_token")

    async def fake_pipeline(**kwargs: Any) -> None:
        calls.append(1)

    monkeypatch.setattr(settings, "feature_chat_websocket_enabled", True)
    monkeypatch.setattr(chat_api, "authenticate_ws_handshake", fake_auth)
    monkeypatch.setattr(chat_api, "_run_ws_chat_pipeline", fake_pipeline)
    ws = _FakeWebSocket()
    await chat_api.chat_websocket(ws, token="tok")  # type: ignore[arg-type]
    return ws, calls


async def test_ws_closed_mode_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    _set_mode(monkeypatch, RateLimitRedisFailureMode.closed)
    ws, calls = await _run_ws(monkeypatch)
    codes = [e["safe_error_code"] for e in ws.sent if e["event"] == "chat.error"]
    assert codes == ["rate_limiter_unavailable"]
    assert calls == []
    assert ws.closed is False


async def test_ws_open_mode_runs_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    _set_mode(monkeypatch, RateLimitRedisFailureMode.open)
    ws, calls = await _run_ws(monkeypatch)
    assert not [e for e in ws.sent if e["event"] == "chat.error"]
    assert calls == [1]


async def test_ws_limited_sends_rate_limit_exceeded(
    monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis
) -> None:
    monkeypatch.setattr(settings, "rate_limit_chat_requests", 0)
    monkeypatch.setattr(redis_module, "redis_client", fake_redis)
    ws, calls = await _run_ws(monkeypatch)
    codes = [e["safe_error_code"] for e in ws.sent if e["event"] == "chat.error"]
    assert codes == ["rate_limit_exceeded"]
    assert calls == []
