"""Graceful shutdown of an API replica (R08-02, contract 5.2.5).

``drain_dropped_runs`` waits for chat runs whose socket dropped (resume grace watchers) and
cancels what is left; ``lifespan`` calls it before closing Redis and the database when
``API_SHUTDOWN_DRAIN_SECONDS`` > 0. uvicorn closes open WebSockets with ``1012`` (service
restart) when shutdown starts, which the frontend treats as retryable.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI

from app.application.chat.transports import ws as ws_transport
from app.clients import redis_client as redis_module
from app.core import lifespan as lifespan_module
from app.core.config import settings


@dataclass
class _Buffer:
    key: str = "rudix:test:chat:resume:v1:k"
    failed: bool = False


@pytest.fixture(autouse=True)
def _grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "chat_ws_resume_grace_seconds", 30)
    monkeypatch.setattr(settings, "chat_resume_poll_ms", 10)
    monkeypatch.setattr(redis_module, "redis_client", None)


def _drop(run: asyncio.Task[None]) -> None:
    ws_transport.keep_run_alive_after_drop(run, ws_transport.WsRunHandle(buffer=_Buffer()))  # type: ignore[arg-type]


async def _run(seconds: float, done: list[str]) -> None:
    await asyncio.sleep(seconds)
    done.append("finished")


async def test_drain_waits_for_a_dropped_run_to_finish() -> None:
    done: list[str] = []
    run = asyncio.create_task(_run(0.05, done))
    _drop(run)
    assert len(ws_transport._GRACE_WATCHERS) == 1

    finished, cancelled = await ws_transport.drain_dropped_runs(2.0)
    assert (finished, cancelled) == (1, 0)
    assert done == ["finished"]
    assert not ws_transport._GRACE_WATCHERS and not ws_transport._DROPPED_RUNS


async def test_drain_with_zero_timeout_cancels_at_once() -> None:
    done: list[str] = []
    run = asyncio.create_task(_run(30, done))
    _drop(run)
    loop = asyncio.get_running_loop()
    started = loop.time()

    finished, cancelled = await ws_transport.drain_dropped_runs(0)
    assert (finished, cancelled) == (0, 1)
    assert loop.time() - started < 1.0
    assert run.cancelled()
    assert done == []
    await asyncio.sleep(0)
    assert not ws_transport._GRACE_WATCHERS and not ws_transport._DROPPED_RUNS


async def test_drain_without_dropped_runs_returns_at_once() -> None:
    assert await ws_transport.drain_dropped_runs(5.0) == (0, 0)


# -- lifespan --------------------------------------------------------------------------------


def _quiet_lifespan(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    """Replace every client init/close in ``lifespan`` with a recorder."""

    def recorder(name: str, *, is_async: bool) -> Callable[..., Any]:
        if is_async:

            async def record_async(*args: Any, **kwargs: Any) -> None:
                del args, kwargs
                calls.append(name)

            return record_async

        def record(*args: Any, **kwargs: Any) -> None:
            del args, kwargs
            calls.append(name)

        return record

    async_names = (
        "init_redis",
        "init_cache_redis",
        "init_rabbitmq",
        "init_qdrant",
        "_reconcile_vector_index",
        "init_neo4j",
        "run_graph_migrations",
        "probe_local_providers",
        "close_redis",
        "close_cache_redis",
        "close_async_qdrant_clients",
        "close_neo4j",
        "stop_loop_lag_monitor",
        "dispose_engine",
    )
    sync_names = (
        "init_sentry",
        "init_langfuse",
        "init_minio",
        "init_clamav",
        "start_loop_lag_monitor",
        "close_rabbitmq",
        "close_qdrant",
        "close_minio",
        "close_clamav",
        "shutdown_langfuse",
    )
    for name in async_names:
        monkeypatch.setattr(lifespan_module, name, recorder(name, is_async=True))
    for name in sync_names:
        monkeypatch.setattr(lifespan_module, name, recorder(name, is_async=False))


async def test_lifespan_drains_a_dropped_run_before_closing_clients(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []
    _quiet_lifespan(monkeypatch, calls)
    monkeypatch.setattr(settings, "api_shutdown_drain_seconds", 2.0)
    done: list[str] = []

    async def run_then_record() -> None:
        await _run(0.05, done)
        calls.append("run_finished")

    caplog.set_level(logging.INFO, logger=lifespan_module.logger.name)
    async with lifespan_module.lifespan(FastAPI()):
        assert "init_cache_redis" in calls
        _drop(asyncio.create_task(run_then_record()))

    assert done == ["finished"]
    assert calls.index("run_finished") < calls.index("close_cache_redis")
    assert calls.index("close_cache_redis") < calls.index("close_redis")
    drain_logs = [r for r in caplog.records if r.getMessage() == "api.shutdown.drain"]
    assert drain_logs and drain_logs[0].finished == 1 and drain_logs[0].cancelled == 0  # type: ignore[attr-defined]


async def test_lifespan_without_drain_keeps_todays_behaviour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _quiet_lifespan(monkeypatch, calls)
    monkeypatch.setattr(settings, "api_shutdown_drain_seconds", 0.0)

    async def must_not_run(timeout: float) -> tuple[int, int]:
        raise AssertionError(f"drain called with {timeout}")

    monkeypatch.setattr(ws_transport, "drain_dropped_runs", must_not_run)
    async with lifespan_module.lifespan(FastAPI()):
        pass
    assert "close_redis" in calls and "dispose_engine" in calls


async def test_failed_drain_still_closes_clients(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []
    _quiet_lifespan(monkeypatch, calls)
    monkeypatch.setattr(settings, "api_shutdown_drain_seconds", 1.0)

    async def broken(timeout: float) -> tuple[int, int]:
        del timeout
        raise RuntimeError("boom")

    monkeypatch.setattr(ws_transport, "drain_dropped_runs", broken)
    caplog.set_level(logging.WARNING, logger=lifespan_module.logger.name)
    async with lifespan_module.lifespan(FastAPI()):
        pass
    assert "close_redis" in calls
    assert any(r.getMessage() == "api.shutdown.drain_failed" for r in caplog.records)


def test_drain_setting_bounds() -> None:
    from pydantic import ValidationError

    from app.core.settings.deployment import DeploymentSettings

    assert DeploymentSettings().api_shutdown_drain_seconds == 0
    assert DeploymentSettings(api_shutdown_drain_seconds=120).api_shutdown_drain_seconds == 120
    with pytest.raises(ValidationError):
        DeploymentSettings(api_shutdown_drain_seconds=121)
    with pytest.raises(ValidationError):
        DeploymentSettings(api_shutdown_drain_seconds=-1)


# -- uvicorn closes open WebSockets with 1012 ------------------------------------------------


async def _echo_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
    assert scope["type"] == "websocket"
    message = await receive()
    assert message["type"] == "websocket.connect"
    await send({"type": "websocket.accept"})
    while True:
        message = await receive()
        if message["type"] == "websocket.disconnect":
            return


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# "auto" is what the API image runs (``uvicorn app.main:app``); with websockets installed
# uvicorn 0.54 resolves it to the sans-I/O implementation.
@pytest.mark.parametrize("ws_impl", ["auto", "websockets", "websockets-sansio"])
async def test_uvicorn_shutdown_closes_open_websockets_with_1012(ws_impl: str) -> None:
    uvicorn = pytest.importorskip("uvicorn")
    try:
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed
    except ImportError:  # pragma: no cover - uvicorn[standard] installs websockets
        pytest.skip("the websockets package (uvicorn[standard]) is not installed")

    port = _free_port()
    config = uvicorn.Config(
        _echo_app, host="127.0.0.1", port=port, ws=ws_impl, lifespan="off", log_level="error"
    )
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started

        async with connect(f"ws://127.0.0.1:{port}/") as client:
            server.should_exit = True
            with pytest.raises(ConnectionClosed) as closed:
                await asyncio.wait_for(client.recv(), timeout=10)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1012
        await asyncio.wait_for(serving, timeout=10)
    finally:
        server.should_exit = True
        if not serving.done():
            serving.cancel()
            await asyncio.gather(serving, return_exceptions=True)
