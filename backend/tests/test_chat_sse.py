"""``POST /api/v1/chat/query/stream`` (R05-03): SSE frames, pre-stream HTTP errors,
disconnect cancellation through the full middleware stack."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from chat_golden_support import _question_usage
from chat_stream_support import (
    TEXT_A,
    StreamingRecordingProvider,
    counter_value,
    histogram_count,
    make_world,
)
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from test_chat_query_api import (
    _auth_headers,
    _seed_quota_policy,
    chat_query_client,  # noqa: F401  (pytest fixture re-export)
)

from app.application.chat.transports import sse
from app.auth.token_codec import create_app_access_token
from app.core.config import settings
from app.core.metrics import CHAT_STREAM_CANCELLED_TOTAL, CHAT_TTFT_SECONDS
from app.interfaces.http import chat as chat_api
from app.main import app
from app.models.chat import ChatMessage, ChatSession
from app.models.usage import UsageEvent

pytestmark = [pytest.mark.asyncio]

STREAM_PATH = "/api/v1/chat/query/stream"


def _headers(world: Any) -> dict[str, str]:
    token = create_app_access_token(
        subject=world.user.external_auth_id,
        organization_id=str(world.organization.id),
        expires_in_seconds=600,
    )
    return _auth_headers(token=token, organization_id=str(world.organization.id))


def _without_request_id(body: dict[str, Any]) -> dict[str, Any]:
    error = dict(body["error"])
    error.pop("request_id", None)
    return {**body, "error": error}


def parse_frames(body: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        frames.append(
            {"id": int(fields["id"]), "event": fields["event"], "data": json.loads(fields["data"])}
        )
    return frames


async def _wait_for_runs() -> None:
    for _ in range(200):
        if not sse._active_runs:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("SSE pipeline task did not finish")


async def test_sse_streams_frames_until_chat_completed(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StreamingRecordingProvider(chunk_size=6)
    world = await make_world(db_session, monkeypatch, provider)
    ttft_before = histogram_count(CHAT_TTFT_SECONDS, transport="sse")

    response = await chat_query_client.post(
        STREAM_PATH,
        headers={**_headers(world), "Accept-Encoding": "gzip"},
        json=world.payload,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert "content-encoding" not in response.headers  # GZip skips text/event-stream
    frames = parse_frames(response.text)
    assert [f["id"] for f in frames] == list(range(1, len(frames) + 1))
    for frame in frames:
        assert frame["data"]["event"] == frame["event"]
        assert frame["data"]["sequence"] == frame["id"]
    names = [f["event"] for f in frames if f["event"] != "activity.step.update"]
    assert names[0] == "chat.request.received" and names[-1] == "chat.completed"
    assert names.index("generation.started") < names.index("generation.delta")
    assert names.index("generation.final") < names.index("chat.completed")
    deltas = "".join(
        f["data"]["payload"]["text"] for f in frames if f["event"] == "generation.delta"
    )
    completed = frames[-1]["data"]["payload"]["response"]
    assert deltas == TEXT_A == completed["answer"]
    conversation_ids = {f["data"]["conversation_id"] for f in frames}
    assert conversation_ids == {completed["chat_session_id"]}
    assert histogram_count(CHAT_TTFT_SECONDS, transport="sse") == ttft_before + 1

    usage = (await db_session.execute(select(UsageEvent))).scalars().all()
    assert [u.event_type for u in usage] == ["chat.completion"]
    assert usage[0].metadata_json["transport"] == "sse"
    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 2


async def test_sse_plan_limit_is_the_same_http_error_as_post_chat(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    await _seed_quota_policy(
        db_session,
        organization_id=world.organization.id,
        limits={"questions": {"soft_limit": 0, "hard_limit": 0, "reset_window": "per_day"}},
    )

    stream = await chat_query_client.post(STREAM_PATH, headers=_headers(world), json=world.payload)
    plain = await chat_query_client.post(
        "/api/v1/chat", headers=_headers(world), json=world.payload
    )

    assert stream.status_code == plain.status_code == 403
    assert _without_request_id(stream.json()) == _without_request_id(plain.json())
    assert not stream.headers["content-type"].startswith("text/event-stream")
    assert provider.calls == []
    await _wait_for_runs()


@pytest.mark.parametrize(
    "extra",
    [
        {"document_ids": ["00000000-0000-4000-8000-0000000000dd"]},
        {"chat_session_id": "00000000-0000-4000-8000-0000000000aa"},
    ],
    ids=["unknown-document", "unknown-session"],
)
async def test_sse_not_found_is_the_same_http_error_as_post_chat(
    extra: dict[str, Any],
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    payload = {**world.payload, **extra}

    stream = await chat_query_client.post(STREAM_PATH, headers=_headers(world), json=payload)
    plain = await chat_query_client.post("/api/v1/chat", headers=_headers(world), json=payload)

    assert stream.status_code == plain.status_code == 404
    assert _without_request_id(stream.json()) == _without_request_id(plain.json())
    await _wait_for_runs()


async def test_sse_failure_after_stage_three_is_a_chat_error_event(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_api._llm_service, "retry_max_attempts", 1)
    provider = StreamingRecordingProvider(fail_kinds=frozenset({"answer"}))
    world = await make_world(db_session, monkeypatch, provider)

    response = await chat_query_client.post(
        STREAM_PATH, headers=_headers(world), json=world.payload
    )

    assert response.status_code == 200
    frames = parse_frames(response.text)
    assert frames[-1]["event"] == "chat.error"
    assert frames[-1]["data"]["safe_error_code"] == "generation_failed"
    assert "chat.completed" not in {f["event"] for f in frames}
    assert await db_session.scalar(select(func.count()).select_from(ChatSession)) == 0


async def test_sse_requires_authentication(chat_query_client: AsyncClient) -> None:  # noqa: F811
    response = await chat_query_client.post(STREAM_PATH, json={"question": "hi"})
    assert response.status_code == 401


class _DisconnectingClient:
    """Raw ASGI peer: sends the request body, then ``http.disconnect`` once the first
    ``generation.delta`` frame has arrived."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self._sent_body = False
        self.messages: list[dict[str, Any]] = []
        self.saw_delta = asyncio.Event()

    async def receive(self) -> dict[str, Any]:
        if not self._sent_body:
            self._sent_body = True
            return {"type": "http.request", "body": self._body, "more_body": False}
        await self.saw_delta.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: dict[str, Any]) -> None:
        self.messages.append(message)
        if b"event: generation.delta" in message.get("body", b""):
            self.saw_delta.set()


@pytest.mark.parametrize("spec_version", ["2.3", "2.4"])
async def test_sse_client_disconnect_cancels_the_run_through_the_middleware_stack(
    spec_version: str,
    chat_query_client: AsyncClient,  # noqa: F811  (settings, db override)
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hold = asyncio.Event()  # never set: the provider stalls mid-stream
    provider = StreamingRecordingProvider(chunk_size=6, hold=hold)
    world = await make_world(db_session, monkeypatch, provider)
    cancelled_before = counter_value(CHAT_STREAM_CANCELLED_TOTAL, transport="sse")
    questions_before = await _question_usage(db_session, world.organization.id)
    headers = [(k.lower().encode(), v.encode()) for k, v in _headers(world).items()]
    peer = _DisconnectingClient(json.dumps(world.payload).encode())
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": STREAM_PATH,
        "raw_path": STREAM_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [*headers, (b"content-type", b"application/json")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }

    await asyncio.wait_for(app(scope, peer.receive, peer.send), timeout=10)
    await _wait_for_runs()

    assert peer.messages[0]["type"] == "http.response.start"
    assert peer.messages[0]["status"] == 200
    assert provider.closed_streams == 1 and provider.finished_streams == 0
    assert counter_value(CHAT_STREAM_CANCELLED_TOTAL, transport="sse") == cancelled_before + 1
    usage = (await db_session.execute(select(UsageEvent))).scalars().all()
    assert [u.event_type for u in usage] == ["chat.completion.cancelled"]
    assert usage[0].metadata_json["transport"] == "sse"
    assert usage[0].metadata_json["usage_estimated"] is True
    assert await db_session.scalar(select(func.count()).select_from(ChatMessage)) == 0
    assert await _question_usage(db_session, world.organization.id) == questions_before


def test_frame_format_matches_the_contract() -> None:
    from app.domains.chat.schemas.chat_ws import ChatWSOutboundEvent

    event = ChatWSOutboundEvent(event="generation.delta", sequence=7, payload={"text": "a\nb"})
    frame = sse.format_sse_frame(event)
    head, data = frame.split("data: ", 1)
    assert head == "id: 7\nevent: generation.delta\n"
    assert data.endswith("\n\n") and "\n" not in data[:-2]
    assert json.loads(data)["payload"] == {"text": "a\nb"}


async def test_keepalive_comment_when_nothing_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ws_chat_heartbeat_interval_seconds", 0)
    queue: asyncio.Queue[Any] = asyncio.Queue()
    run = asyncio.create_task(asyncio.sleep(10))
    frames = sse._frames(queue, run)
    assert await frames.__anext__() == ": keep-alive\n\n"
    await frames.aclose()
    await asyncio.sleep(0)
    assert run.cancelled()


async def test_request_cancelled_before_the_stream_starts_cancels_the_run(
    chat_query_client: AsyncClient,  # noqa: F811
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from chat_stream_support import principal_for

    from app.domains.chat.schemas.chat import ChatQueryRequest

    provider = StreamingRecordingProvider()
    world = await make_world(db_session, monkeypatch, provider)
    entered = asyncio.Event()

    async def stalled_quota(*_args: Any, **_kwargs: Any) -> None:
        entered.set()
        await asyncio.Event().wait()  # stage 1 never finishes

    opening = asyncio.create_task(
        sse.open_sse_query(
            payload=ChatQueryRequest.model_validate(world.payload),
            principal=principal_for(world),
            request_id="sse-cancel-early",
            session_factory=chat_api.SessionLocal,
            ensure_quota=stalled_quota,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    (run,) = list(sse._active_runs)
    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening
    await _wait_for_runs()
    assert run.cancelled()
    assert provider.calls == []
