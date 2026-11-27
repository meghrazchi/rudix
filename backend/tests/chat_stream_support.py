"""Streaming fakes and transport drivers for the R05-03 tests.

``StreamingRecordingProvider`` is the golden recording provider with a ``stream()`` that
yields the scripted answer in small pieces with ``asyncio.sleep`` between them, so the
first ``generation.delta`` can be observed while the provider is still mid-stream.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from chat_golden_providers import _KIND_TOKENS, RecordingChatProvider, prompt_kind
from chat_golden_support import GoldenWorld, SeedDoc, seed_documents
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import _seed_principal
from test_chat_transport_parity import _SessionLocalOverride

from app.core.config import settings
from app.domains.ai.providers.errors import ProviderTimeoutError
from app.domains.ai.providers.protocols import ChatCompletionChunk, ChatCompletionRequest
from app.interfaces.http import chat as chat_api
from app.models.enums import OrganizationRole

QUESTION = "How much annual leave is provided?"
TEXT_A = "Employees receive twenty days of annual leave."


class StreamingRecordingProvider(RecordingChatProvider):
    def __init__(
        self,
        *,
        chunk_size: int = 7,
        delay_seconds: float = 0.01,
        fail_first_stream_after: int | None = None,
        hold: asyncio.Event | None = None,
        hold_at: int = 4,
        report_usage: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.chunk_size = chunk_size
        self.delay_seconds = delay_seconds
        self.fail_first_stream_after = fail_first_stream_after
        self.hold = hold
        self.hold_at = hold_at
        self.report_usage = report_usage
        self.stream_calls = 0
        self.active_streams = 0
        self.finished_streams = 0
        self.closed_streams = 0
        self.pieces_yielded = 0

    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        kind = prompt_kind(request.prompt)
        self.calls.append((kind, request))
        if kind in self._fail_kinds:
            raise ProviderTimeoutError(f"scripted {kind} failure")
        content = self._responders[kind](request.prompt)
        self.stream_calls += 1
        call_number = self.stream_calls
        self.active_streams += 1
        try:
            pieces = [
                content[i : i + self.chunk_size] for i in range(0, len(content), self.chunk_size)
            ]
            for index, piece in enumerate(pieces):
                if index > 0:
                    await asyncio.sleep(self.delay_seconds)
                if call_number == 1 and index == self.fail_first_stream_after:
                    raise ProviderTimeoutError("scripted mid-stream failure")
                if index == self.hold_at and self.hold is not None:
                    await self.hold.wait()
                self.pieces_yielded += 1
                yield ChatCompletionChunk(text_delta=piece, model=settings.openai_llm_model)
            if self.report_usage:
                prompt_tokens, completion_tokens = _KIND_TOKENS[kind]
                yield ChatCompletionChunk(
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
                )
            self.finished_streams += 1
        finally:
            self.active_streams -= 1
            self.closed_streams += 1


class RecordingSocket:
    """Fake WebSocket: records each event with the provider's stream state at send time."""

    def __init__(self, provider: StreamingRecordingProvider | None = None) -> None:
        self.provider = provider
        self.events: list[dict[str, Any]] = []
        self.mid_stream: list[bool] = []
        self.sent_event = asyncio.Event()

    async def send_text(self, data: str) -> None:
        self.events.append(json.loads(data))
        self.mid_stream.append(bool(self.provider and self.provider.active_streams > 0))
        self.sent_event.set()

    def names(self) -> list[str]:
        return [e["event"] for e in self.events if e["event"] != "activity.step.update"]

    def of(self, name: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["event"] == name]

    def deltas(self) -> str:
        return "".join(e["payload"]["text"] for e in self.of("generation.delta"))

    async def wait_for(self, name: str, timeout: float = 5.0) -> None:
        async def _wait() -> None:
            while not self.of(name):
                self.sent_event.clear()
                await self.sent_event.wait()

        await asyncio.wait_for(_wait(), timeout)


async def make_world(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    provider: RecordingChatProvider,
    *,
    docs: list[SeedDoc] | None = None,
    role: OrganizationRole = OrganizationRole.member,
) -> GoldenWorld:
    from chat_golden_providers import install_providers

    user, organization, _ = await _seed_principal(db_session, role=role)
    install_providers(monkeypatch, provider)  # type: ignore[arg-type]
    world = GoldenWorld(
        user=user,
        organization=organization,
        role=role,
        provider=provider,
        payload={"question": QUESTION, "top_k": 3, "rerank": False},
    )
    await seed_documents(
        db_session, world, docs if docs is not None else [SeedDoc("a", TEXT_A, 0.92)]
    )
    monkeypatch.setattr(chat_api, "SessionLocal", _SessionLocalOverride(db_session))
    return world


def principal_for(world: GoldenWorld) -> chat_api.AuthenticatedPrincipal:
    return chat_api.AuthenticatedPrincipal(
        user_id=str(world.user.id),
        organization_id=str(world.organization.id),
        email=world.user.email,
        roles=[world.role.value],
        auth_provider="app",
    )


async def run_ws(world: GoldenWorld, socket: RecordingSocket) -> None:
    await chat_api._run_ws_chat_pipeline(
        websocket=socket,  # type: ignore[arg-type]
        payload={"chat_session_id": None, **world.payload},
        principal=principal_for(world),
        request_id="ws-stream",
        sequence_start=0,
    )


def histogram_count(histogram: Any, **labels: str) -> float:
    for metric in histogram.collect():
        for sample in metric.samples:
            if sample.name.endswith("_count") and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return float(sample.value)
    return 0.0


def counter_value(counter: Any, **labels: str) -> float:
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.name.endswith("_total") and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return float(sample.value)
    return 0.0
