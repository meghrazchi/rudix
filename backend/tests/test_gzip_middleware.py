"""R04-11: GZip middleware compresses large JSON and leaves event streams alone."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app, attach_gzip_middleware


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
async def test_minimum_size_threshold_is_respected_on_real_app() -> None:
    """The BaseHTTPMiddleware layers re-stream bodies; GZip must sit inside them."""
    probe_path = "/__gzip_small_probe"
    before = list(app.router.routes)

    @app.get(probe_path, include_in_schema=False)
    async def _small() -> dict[str, str]:
        return {"ok": "yes"}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(probe_path, headers={"Accept-Encoding": "gzip"})
    finally:
        app.router.routes[:] = before

    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == str(len(response.content))
    assert response.json() == {"ok": "yes"}


def test_gzip_middleware_is_inside_the_http_middleware_layers() -> None:
    names = [m.cls.__name__ for m in app.user_middleware]
    # user_middleware is outermost first; GZip must come after the BaseHTTPMiddleware layers.
    assert names.index("GZipMiddleware") > max(
        i for i, name in enumerate(names) if name == "BaseHTTPMiddleware"
    )


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


@pytest.mark.parametrize(("minimum_bytes", "installed"), [(0, False), (1024, True)])
def test_attach_gzip_middleware_respects_setting(minimum_bytes: int, installed: bool) -> None:
    target = FastAPI()
    attach_gzip_middleware(target, minimum_bytes)

    gzip = [m for m in target.user_middleware if m.cls is GZipMiddleware]
    assert bool(gzip) is installed
    if installed:
        assert gzip[0].kwargs == {"minimum_size": minimum_bytes, "compresslevel": 5}
