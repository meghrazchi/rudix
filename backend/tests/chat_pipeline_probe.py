"""Connection probes and stub providers for the chat session-lifetime tests (R05-02)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from chat_golden_providers import RecordingChatProvider, prompt_kind
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.models import AuthenticatedPrincipal
from app.domains.ai.providers.protocols import ChatCompletionRequest, ChatCompletionResponse
from app.interfaces.http import chat as chat_api


class PoolProbe:
    """Counts connections checked out of an engine's pool (checkouts minus checkins).

    Attach it while nothing is checked out; ``checked_out`` is then the number of
    connections the code under test holds at this moment.
    """

    def __init__(self, engine: AsyncEngine | Engine) -> None:
        self._engine = engine.sync_engine if isinstance(engine, AsyncEngine) else engine
        self.checked_out = 0
        self.peak = 0

    def _on_checkout(self, *_args: Any) -> None:
        self.checked_out += 1
        self.peak = max(self.peak, self.checked_out)

    def _on_checkin(self, *_args: Any) -> None:
        self.checked_out -= 1

    def __enter__(self) -> PoolProbe:
        event.listen(self._engine, "checkout", self._on_checkout)
        event.listen(self._engine, "checkin", self._on_checkin)
        return self

    def __exit__(self, *_exc: object) -> None:
        event.remove(self._engine, "checkout", self._on_checkout)
        event.remove(self._engine, "checkin", self._on_checkin)


@dataclass
class Observation:
    kind: str
    checked_out: int
    request_in_transaction: bool | None


class ProbingChatProvider(RecordingChatProvider):
    """The golden recording provider plus a check inside ``complete()``.

    Every call records, while the stubbed model is "generating" (before the optional
    sleep), how many connections the probe sees checked out and, when a request session is
    given, whether it has an open transaction.
    """

    def __init__(
        self,
        *,
        probe: PoolProbe | None = None,
        request_session: Any = None,
        delay_seconds: float = 0.0,
        fail_kinds: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(fail_kinds=fail_kinds)
        self.probe = probe
        self.request_session = request_session
        self.delay_seconds = delay_seconds
        self.observations: list[Observation] = []

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        in_tx = None if self.request_session is None else self.request_session.in_transaction()
        self.observations.append(
            Observation(
                kind=prompt_kind(request.prompt),
                checked_out=self.probe.checked_out if self.probe is not None else -1,
                request_in_transaction=in_tx,
            )
        )
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return await super().complete(request)


class ProbingEmbeddingProvider:
    """A fake embedding provider that records, per call, the connections the probe sees
    checked out and whether the request session has an open transaction."""

    def __init__(self, inner: Any, *, probe: PoolProbe, request_session: Any = None) -> None:
        self._inner = inner
        self.probe = probe
        self.request_session = request_session
        self.observations: list[tuple[int, bool | None]] = []

    async def embed(self, request: Any) -> Any:
        in_tx = None if self.request_session is None else self.request_session.in_transaction()
        self.observations.append((self.probe.checked_out, in_tx))
        return await self._inner.embed(request)


def ws_principal(user_id: object, organization_id: object, role: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=str(user_id),
        organization_id=str(organization_id),
        email="probe@example.com",
        roles=[role],
        auth_provider="app",
    )


class CollectingWebSocket:
    def __init__(self) -> None:
        self.sent_texts: list[str] = []

    async def send_text(self, data: str) -> None:
        self.sent_texts.append(data)

    @property
    def events(self) -> list[dict[str, Any]]:
        return [json.loads(text) for text in self.sent_texts]


async def run_ws_question(
    *,
    principal: AuthenticatedPrincipal,
    payload: dict[str, Any],
    request_id: str = "ws-probe",
) -> CollectingWebSocket:
    websocket = CollectingWebSocket()
    await chat_api._run_ws_chat_pipeline(
        websocket=websocket,  # type: ignore[arg-type]
        payload={"chat_session_id": None, **payload},
        principal=principal,
        request_id=request_id,
        sequence_start=0,
    )
    return websocket
