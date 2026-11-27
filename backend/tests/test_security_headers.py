from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from app.core.security_headers import SecurityHeadersMiddleware
from app.main import app


def _starlette_app(*, hsts_enabled: bool) -> FastAPI:
    sub = FastAPI()

    @sub.get("/plain")
    async def plain() -> dict[str, str]:
        return {"ok": "yes"}

    @sub.get("/custom")
    async def custom(response: Response) -> dict[str, str]:
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return {"ok": "yes"}

    sub.add_middleware(SecurityHeadersMiddleware, hsts_enabled=hsts_enabled)
    return sub


def test_health_has_security_headers_without_hsts() -> None:
    response = TestClient(app).get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-frame-options"] == "DENY"
    assert "strict-transport-security" not in response.headers


def test_hsts_added_when_enabled() -> None:
    response = TestClient(_starlette_app(hsts_enabled=True)).get("/plain")

    assert response.headers["strict-transport-security"] == "max-age=31536000"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_hsts_absent_when_disabled() -> None:
    response = TestClient(_starlette_app(hsts_enabled=False)).get("/plain")

    assert "strict-transport-security" not in response.headers


def test_existing_header_is_not_overwritten() -> None:
    response = TestClient(_starlette_app(hsts_enabled=False)).get("/custom")

    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_websocket_scope_passes_through() -> None:
    seen: list[Message] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "websocket.accept"})

    async def receive() -> Message:
        return {"type": "websocket.connect"}

    async def send(message: Message) -> None:
        seen.append(message)

    middleware = SecurityHeadersMiddleware(inner, hsts_enabled=True)
    await middleware({"type": "websocket"}, receive, send)

    assert seen == [{"type": "websocket.accept"}]


def test_docs_still_served() -> None:
    response = TestClient(app).get("/docs")

    assert response.status_code == 200
    assert response.headers["x-frame-options"] == "DENY"
