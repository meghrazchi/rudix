"""Drivers for the resumable WebSocket chat tests (R05-13)."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

import pytest

from app.application.chat import ws_auth
from app.application.chat.transports import ws as ws_transport
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.interfaces.http import chat as chat_api


class DroppableSocket:
    """Fake WebSocket driven by the test. ``drop()`` closes it: later sends fail (like a
    socket whose peer is gone) and the connection loop sees a disconnect."""

    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.client = None
        self.events: list[dict[str, Any]] = []
        self.closed = False
        self._incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self._sent = asyncio.Event()

    async def accept(self) -> None:
        return None

    async def close(self, code: int = 1000, reason: str = "") -> None:
        return None

    async def send_text(self, text: str) -> None:
        if self.closed:
            raise RuntimeError("socket closed")
        self.events.append(json.loads(text))
        self._sent.set()

    async def receive_text(self) -> str:
        from fastapi import WebSocketDisconnect

        item = await self._incoming.get()
        if item is None:
            raise WebSocketDisconnect()
        return item

    def push(self, command: str, payload: dict[str, Any] | None = None) -> None:
        self._incoming.put_nowait(json.dumps({"command": command, "payload": payload}))

    def drop(self) -> None:
        self.closed = True
        self._incoming.put_nowait(None)

    def names(self) -> list[str]:
        return [e["event"] for e in self.events if e["event"] != "activity.step.update"]

    def of(self, name: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == name]

    def run_events(self) -> list[dict[str, Any]]:
        """Events of the run (they carry a ``stream_sequence``)."""
        return [e for e in self.events if e.get("stream_sequence") is not None]

    def deltas(self) -> str:
        return "".join(e["payload"]["text"] for e in self.of("generation.delta"))

    async def wait_for(self, name: str, timeout: float = 5.0) -> None:
        async def _wait() -> None:
            while name not in self.names():
                self._sent.clear()
                await self._sent.wait()

        await asyncio.wait_for(_wait(), timeout)


def install_ws(monkeypatch: pytest.MonkeyPatch, principals: list[AuthenticatedPrincipal]) -> None:
    """Connections authenticate as the given principals, in order."""
    queue = list(principals)

    async def fake_auth(**_kwargs: Any) -> ws_auth.WsAuthResult:
        return ws_auth.WsAuthResult(principal=queue.pop(0), method="ticket")

    monkeypatch.setattr(settings, "feature_chat_websocket_enabled", True)
    monkeypatch.setattr(settings, "chat_resume_poll_ms", 10)
    monkeypatch.setattr(chat_api, "authenticate_ws_handshake", fake_auth)


def connect(socket: DroppableSocket) -> asyncio.Task[None]:
    return asyncio.create_task(chat_api.chat_websocket(socket, ticket="t"))  # type: ignore[arg-type]


async def wait_for_watchers(timeout: float = 5.0) -> None:
    """Wait until every grace watcher (dropped runs) has finished."""
    watchers = list(ws_transport._GRACE_WATCHERS)
    if watchers:
        await asyncio.wait_for(asyncio.gather(*watchers), timeout)


def stranger(principal: AuthenticatedPrincipal, *, same_org: bool) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(uuid4()),
        organization_id=principal.organization_id if same_org else str(uuid4()),
        email="other@example.com",
        roles=list(principal.roles or []),
        auth_provider="app",
    )


def stream_sequences(events: list[dict[str, Any]]) -> list[int]:
    return [int(e["stream_sequence"]) for e in events if e.get("stream_sequence") is not None]
