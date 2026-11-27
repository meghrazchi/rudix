"""R04-11: GZip middleware compresses large JSON and leaves event streams alone."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_large_json_is_gzip_encoded() -> None:
    """Uses a temporary route on the real app so the production middleware stack applies."""
    assert settings.http_gzip_minimum_bytes == 1024
    probe_path = "/__gzip_probe"
    before = list(app.router.routes)

    @app.get(probe_path, include_in_schema=False)
    async def _probe() -> dict[str, list[str]]:
        return {"items": ["lorem ipsum dolor sit amet"] * 200}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(probe_path, headers={"Accept-Encoding": "gzip"})
            identity = await client.get(probe_path, headers={"Accept-Encoding": "identity"})
    finally:
        app.router.routes[:] = before

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert len(response.json()["items"]) == 200  # httpx transparently decodes
    assert "content-encoding" not in identity.headers


@pytest.mark.asyncio
async def test_minimum_size_threshold_is_respected() -> None:
    mini = FastAPI()
    mini.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

    @mini.get("/small")
    async def small() -> dict[str, str]:
        return {"ok": "yes"}

    async with AsyncClient(
        transport=ASGITransport(app=mini), base_url="http://testserver"
    ) as client:
        response = await client.get("/small", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers


@pytest.mark.asyncio
async def test_event_stream_is_not_buffered_or_compressed() -> None:
    mini = FastAPI()
    mini.add_middleware(GZipMiddleware, minimum_size=10, compresslevel=5)

    async def events() -> AsyncIterator[str]:
        for index in range(3):
            yield f"data: {'x' * 50} {index}\n\n"

    @mini.get("/sse")
    async def sse() -> StreamingResponse:
        return StreamingResponse(events(), media_type="text/event-stream")

    async with AsyncClient(
        transport=ASGITransport(app=mini), base_url="http://testserver"
    ) as client:
        response = await client.get("/sse", headers={"Accept-Encoding": "gzip"})

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.text.count("data: ") == 3


@pytest.mark.asyncio
async def test_gzip_disabled_when_minimum_bytes_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    import app.main as main_module

    monkeypatch.setattr(settings, "http_gzip_minimum_bytes", 0)
    reloaded = importlib.reload(main_module)
    try:
        assert all(m.cls is not GZipMiddleware for m in reloaded.app.user_middleware)
    finally:
        monkeypatch.undo()
        importlib.reload(main_module)
