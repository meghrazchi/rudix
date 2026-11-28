"""Span redaction: allowlisted attributes only, no content leaves the process (R08-10)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from unittest.mock import MagicMock
from uuid import uuid4

import httpx
import pytest
import redis.asyncio as redis_asyncio
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from inmemory_qdrant import AsyncInMemoryQdrant
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Link, SpanContext, SpanKind, Status, StatusCode
from qdrant_client.http.models import PointStruct
from sqlalchemy import text

from app.clients import qdrant_client as qdrant_module
from app.core import logging as app_logging
from app.core import tracing
from app.core.tracing_redaction import (
    MAX_VALUE_LENGTH,
    RedactingSpanExporter,
    is_allowed_attribute,
    redact_attributes,
    redact_span,
    strip_query,
)
from app.db import session as db_session
from app.domains.ai.providers.protocols import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from app.domains.ai.providers.resilience import BreakerRegistry, ResilientChatProvider
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.documents.services.qdrant_service import QdrantService
from tests.tracing_support import span_text, tracing_config, tracing_session

SENTINELS = {
    "prompt": "SENTINEL-PROMPT-7f3a",
    "document": "SENTINEL-DOCTEXT-91c2",
    "answer": "SENTINEL-ANSWER-55d0",
    "sql": "SENTINEL-SQL-0b1e",
    "redis": "SENTINEL-REDIS-c4a8",
    "authorization": "SENTINEL-BEARER-2d6f",
    "cookie": "SENTINEL-COOKIE-e9b7",
    "query": "SENTINEL-QUERY-3a90",
    "url": "SENTINEL-URLKEY-8c15",
    "exception": "SENTINEL-EXC-6f42",
    "body": "SENTINEL-BODY-1d77",
}


# -- unit ----------------------------------------------------------------------------------


def test_allowlist_and_denied_name_parts() -> None:
    assert is_allowed_attribute("http.route")
    assert is_allowed_attribute("rpc.service")
    assert is_allowed_attribute("rudix.request_id")
    assert not is_allowed_attribute("db.statement")
    assert not is_allowed_attribute("url.full")
    assert not is_allowed_attribute("rpc.token")  # denied word beats the prefix
    assert not is_allowed_attribute("rudix.prompt")
    assert not is_allowed_attribute("http.request.header.cookie")


def test_values_lose_query_strings_and_are_bounded() -> None:
    assert strip_query("https://h/p?api_key=x#frag") == "https://h/p"
    attrs = redact_attributes(
        {
            "server.address": "h" * 1000,
            "rudix.outcome": "ok?debug=1",
            "http.status_code": 200,
            "rpc.ids": ["a?x=1", "b"],
            "rpc.numbers": [1, 2],
            "rpc.mixed": ["a", 1],
            "rpc.object": object(),
            "db.statement": "SELECT secret",
        }
    )
    assert attrs == {
        "server.address": "h" * MAX_VALUE_LENGTH,
        "rudix.outcome": "ok",
        "http.status_code": 200,
        "rpc.ids": ("a", "b"),
        "rpc.numbers": (1, 2),
    }
    assert redact_attributes(None) == {}


def test_redact_span_strips_events_links_and_status() -> None:
    context = SpanContext(1, 2, is_remote=False)
    span = ReadableSpan(
        name="GET /p?token=abc",
        context=context,
        attributes={"http.route": "/p", "http.target": "/p?token=abc"},
        events=[
            Event(
                "exception",
                {
                    "exception.type": "ValueError",
                    "exception.message": "boom",
                    "exception.stacktrace": "Traceback",
                },
            ),
            Event("exception", {"exception.message": "no type"}),
            Event("note", {"rudix.outcome": "ok", "message": "drop"}),
        ],
        links=[Link(context, {"rudix.request_id": "r", "text": "drop"})],
        kind=SpanKind.SERVER,
        status=Status(StatusCode.ERROR, "ValueError: boom"),
    )
    clean = redact_span(span)
    assert clean.name == "GET /p"
    assert clean.attributes == {"http.route": "/p"}
    assert [dict(e.attributes or {}) for e in clean.events] == [
        {"exception.type": "ValueError"},
        {},
        {"rudix.outcome": "ok"},
    ]
    assert dict(clean.links[0].attributes or {}) == {"rudix.request_id": "r"}
    assert clean.status.status_code == StatusCode.ERROR
    assert clean.status.description is None
    assert clean.context == context and clean.kind == SpanKind.SERVER


def test_redacting_exporter_delegates() -> None:
    inner = MagicMock()
    inner.export.return_value = SpanExportResult.SUCCESS
    inner.force_flush.return_value = True
    exporter = RedactingSpanExporter(inner)
    span = ReadableSpan(name="x", attributes={"db.statement": "SELECT 1"})
    assert exporter.export([span]) == SpanExportResult.SUCCESS
    [exported] = inner.export.call_args.args[0]
    assert exported.attributes == {}
    assert exporter.force_flush(10) is True
    exporter.shutdown()
    inner.shutdown.assert_called_once_with()


# -- a chat-like request through every instrumentation ---------------------------------------


class _FakeLLM:
    _model_name = "fake-model"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        if self.fail:
            raise ValueError(f"provider rejected {request.prompt}")
        return ChatCompletionResponse(
            content=SENTINELS["answer"],
            model="fake-model",
            prompt_tokens=3,
            completion_tokens=2,
            total_tokens=5,
            latency_ms=1,
        )


class _StreamingLLM(_FakeLLM):
    async def stream(self, request: ChatCompletionRequest) -> AsyncIterator[ChatCompletionChunk]:
        yield ChatCompletionChunk(text_delta=SENTINELS["answer"])


async def _chat_like_work(qdrant: AsyncInMemoryQdrant) -> None:
    # SQL through an engine created after init (the creation hook instruments it).
    engine = db_session.create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn:
        await conn.execute(text(f"SELECT '{SENTINELS['sql']}'"))
    await engine.dispose()
    # Redis: nothing listens on port 1; the span is recorded with the error.
    client = redis_asyncio.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    with pytest.raises(redis_asyncio.ConnectionError):
        await client.set("session:key", SENTINELS["redis"])
    await client.aclose()
    # httpx with a credential in the query string.
    async with httpx.AsyncClient(timeout=0.5) as http:
        with pytest.raises(httpx.ConnectError):
            await http.get(f"http://127.0.0.1:1/v1/models?api_key={SENTINELS['url']}")
    # LLM wrapper: prompt and answer must never reach a span.
    request = ChatCompletionRequest(prompt=SENTINELS["prompt"], model="fake-model")
    registry = BreakerRegistry()
    llm = ResilientChatProvider(_FakeLLM(), "openai", registry=registry)
    response = await llm.complete(request)
    assert response.content == SENTINELS["answer"]
    failing = ResilientChatProvider(_FakeLLM(fail=True), "openai", registry=registry)
    with pytest.raises(ValueError):
        await failing.complete(request)
    streaming = ResilientChatProvider(_StreamingLLM(), "local", registry=registry)
    assert [c.text_delta async for c in streaming.stream(request)] == [SENTINELS["answer"]]
    fallback = ResilientChatProvider(_FakeLLM(), "local", registry=registry)
    assert [c.text_delta async for c in fallback.stream(request)] == [SENTINELS["answer"]]
    # Qdrant write and search with document text in the payload.
    org = uuid4()
    point = PointStruct(
        id=str(uuid4()),
        vector=[0.1, 0.2],
        payload={
            "organization_id": str(org),
            "document_id": str(uuid4()),
            "chunk_id": str(uuid4()),
            "filename": "a.txt",
            "text": SENTINELS["document"],
        },
    )
    await QdrantService()._request("upsert", collection_name="rudix-docs", points=[point])
    candidates = await QueryRetrievalService(qdrant_collection="rudix-docs").aretrieve_candidates(
        query_vector=[0.1, 0.2],
        organization_id=org,
        document_ids=None,
        initial_top_k=3,
        qdrant_client=qdrant,
    )
    assert [c.text for c in candidates] == [SENTINELS["document"]]


def _app(qdrant: AsyncInMemoryQdrant) -> FastAPI:
    app = FastAPI()
    app_logging.attach_access_log_middleware(app)

    @app.post("/api/v1/chat/sessions/{session_id}/messages")
    async def chat(session_id: str, request: Request) -> dict[str, str]:
        await request.body()
        await _chat_like_work(qdrant)
        return {"answer": SENTINELS["answer"], "session": session_id}

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError(SENTINELS["exception"])

    return app


@pytest.fixture
def qdrant(monkeypatch: pytest.MonkeyPatch) -> AsyncInMemoryQdrant:
    client = AsyncInMemoryQdrant()
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(qdrant_module, "get_async_write_client", lambda: client)
    return client


def test_chat_like_request_exports_no_content(qdrant: AsyncInMemoryQdrant) -> None:
    app = _app(qdrant)
    raw = InMemorySpanExporter()
    original_create = db_session.create_async_engine
    with tracing_session() as exporter:
        provider = tracing.tracer_provider()
        assert provider is not None
        provider.add_span_processor(SimpleSpanProcessor(raw))  # unredacted control
        assert db_session.create_async_engine is not original_create
        tracing.instrument_fastapi_app(app, tracing_config())
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                f"/api/v1/chat/sessions/s1/messages?q={SENTINELS['query']}",
                json={"question": SENTINELS["body"]},
                headers={
                    "Authorization": f"Bearer {SENTINELS['authorization']}",
                    "Cookie": f"rudix_session={SENTINELS['cookie']}",
                    "X-Request-ID": "req-redaction",
                },
            )
            assert response.status_code == 200
            assert client.get("/api/v1/boom").status_code == 500
        FastAPIInstrumentor.uninstrument_app(app)
    assert db_session.create_async_engine is original_create  # hook removed on shutdown

    exported = exporter.get_finished_spans()
    names = {span.name for span in exported}
    assert {"rudix.llm.call", "rudix.qdrant.search", "rudix.qdrant.upsert"} <= names
    systems = {(span.attributes or {}).get("db.system") for span in exported}
    assert {"sqlite", "redis"} <= systems
    assert any((s.attributes or {}).get("server.address") == "127.0.0.1" for s in exported)
    llm_spans = [s for s in exported if s.name == "rudix.llm.call"]
    assert {(s.attributes or {}).get("rudix.outcome") for s in llm_spans} == {"ok", "error"}
    assert all((s.attributes or {}).get("rudix.llm.model") == "fake-model" for s in llm_spans)
    search = next(s for s in exported if s.name == "rudix.qdrant.search")
    assert (search.attributes or {}).get("rudix.qdrant.collection") == "rudix-docs"

    # The control proves the sentinels were really offered to the exporter.
    raw_text = "\n".join(span_text(span) for span in raw.get_finished_spans())
    for key in ("sql", "url", "query", "exception"):
        assert SENTINELS[key] in raw_text, key

    for span in exported:
        blob = span_text(span)
        for key, sentinel in SENTINELS.items():
            assert sentinel not in blob, (key, span.name)
        for event in span.events:
            if event.name == "exception":
                assert set(event.attributes or {}) <= {"exception.type"}
        for name in span.attributes or {}:
            assert is_allowed_attribute(name), name

    boom = next(
        s
        for s in exported
        if s.kind == SpanKind.SERVER and (s.attributes or {}).get("http.route") == "/api/v1/boom"
    )
    assert [dict(e.attributes or {}) for e in boom.events] == [{"exception.type": "RuntimeError"}]
    assert boom.status.status_code == StatusCode.ERROR and boom.status.description is None
    chat = next(s for s in exported if s.kind == SpanKind.SERVER and s.name.startswith("POST"))
    assert (chat.attributes or {}).get("rudix.request_id") == "req-redaction"


def test_disabled_path_records_nothing(
    qdrant: AsyncInMemoryQdrant, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    original_create = db_session.create_async_engine
    assert tracing.tracer_provider() is None
    with TestClient(_app(qdrant)) as client:
        response = client.post("/api/v1/chat/sessions/s1/messages", json={})
        assert response.status_code == 200
    assert db_session.create_async_engine is original_create
    assert not any(r.getMessage().startswith("tracing.") for r in caplog.records)


def test_existing_engines_are_instrumented(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    replica = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(db_session, "_reporting_engine", replica, raising=False)

    async def query() -> None:
        async with replica.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await replica.dispose()

    with tracing_session(
        tracing_instrument_redis=False,
        tracing_instrument_httpx=False,
        tracing_instrument_celery=False,
    ) as exporter:
        asyncio.run(query())
    systems = [(s.attributes or {}).get("db.system") for s in exporter.get_finished_spans()]
    assert "sqlite" in systems


def test_search_collection_label_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    service = QueryRetrievalService()
    assert service._collection_label([0.1]) is None  # tracing off: not computed

    def unknown(_: object) -> str:
        raise LookupError("no generation")

    monkeypatch.setattr(service, "search_collection", unknown)
    with tracing_session():
        assert service._collection_label([0.1]) is None
    named = QueryRetrievalService(qdrant_collection="docs")
    with tracing_session():
        assert named._collection_label([0.1]) == "docs"
