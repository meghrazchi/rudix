from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.error_codes import DETAIL_ERROR_CODES, STATUS_ERROR_CODES, code_for
from app.core.errors import INTERNAL_ERROR_MESSAGE, register_exception_handlers
from app.core.logging import attach_access_log_middleware


class _Payload(BaseModel):
    count: int


def _dep_forbidden() -> None:
    raise HTTPException(status_code=403, detail="Invalid organization context")


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    attach_access_log_middleware(app)

    @app.get("/missing")
    async def missing() -> None:
        raise HTTPException(status_code=404, detail="Document not found")

    @app.get("/forbidden", dependencies=[Depends(_dep_forbidden)])
    async def forbidden() -> dict[str, str]:
        return {}

    @app.get("/unauth")
    async def unauth() -> None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/limited")
    async def limited() -> None:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limit_exceeded", "message": "Slow down"},
            headers={"Retry-After": "7", "X-RateLimit-Limit": "5"},
        )

    @app.get("/conflict-unknown")
    async def conflict_unknown() -> None:
        raise HTTPException(status_code=409, detail="Something unmapped")

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail="short and stout")

    @app.get("/timeout")
    async def timeout() -> None:
        raise HTTPException(status_code=504)

    @app.get("/not-modified")
    async def not_modified() -> None:
        raise HTTPException(status_code=304)

    @app.post("/validate")
    async def validate(payload: _Payload) -> dict[str, int]:
        return {"count": payload.count}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret-internal-detail /srv/app/db.py")

    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


def test_404_uses_registry_code_and_keeps_detail(client: TestClient) -> None:
    response = client.get("/missing")
    body = response.json()
    assert response.status_code == 404
    assert body["detail"] == "Document not found"
    assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert body["error"]["message"] == "Document not found"
    assert body["error"]["details"] is None
    assert body["error"]["request_id"] == response.headers["X-Request-ID"]


def test_403_from_dependency(client: TestClient) -> None:
    body = client.get("/forbidden").json()
    assert body["error"]["code"] == "INVALID_ORGANIZATION_CONTEXT"
    assert body["detail"] == "Invalid organization context"


def test_401_preserves_www_authenticate_and_falls_back_to_status_code(
    client: TestClient,
) -> None:
    response = client.get("/unauth")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.json()["detail"] == "Not authenticated"


def test_unmapped_string_detail_uses_status_fallback(client: TestClient) -> None:
    body = client.get("/conflict-unknown").json()
    assert body["error"]["code"] == "CONFLICT"
    assert body["detail"] == "Something unmapped"


def test_dict_detail_keeps_its_code_and_headers(client: TestClient) -> None:
    response = client.get("/limited")
    body = response.json()
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert body["error"]["code"] == "rate_limit_exceeded"
    assert body["error"]["message"] == "Slow down"
    assert body["error"]["details"] == {"code": "rate_limit_exceeded", "message": "Slow down"}
    assert body["detail"] == body["error"]["details"]


def test_unknown_status_and_empty_detail_fall_back(client: TestClient) -> None:
    assert client.get("/teapot").json()["error"]["code"] == "BAD_REQUEST"
    gateway = client.get("/timeout").json()
    assert gateway["error"]["code"] == "INTERNAL_ERROR"
    assert gateway["error"]["message"] == "Gateway Timeout"
    assert gateway["detail"] == "Gateway Timeout"


def test_bodyless_status_has_no_body(client: TestClient) -> None:
    response = client.get("/not-modified")
    assert response.status_code == 304
    assert response.content == b""


def test_validation_error_keeps_list_detail(client: TestClient) -> None:
    response = client.post("/validate", json={"count": "nope"})
    body = response.json()
    assert response.status_code == 422
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert isinstance(body["detail"], list)
    assert body["detail"][0]["loc"] == ["body", "count"]
    assert body["error"]["details"] == body["detail"]


def test_unhandled_exception_is_generic_and_leaks_nothing(client: TestClient) -> None:
    response = client.get("/boom", headers={"X-Request-ID": "req-123"})
    text = response.text
    assert response.status_code == 500
    assert "secret-internal-detail" not in text
    assert "Traceback" not in text
    assert "RuntimeError" not in text
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == INTERNAL_ERROR_MESSAGE
    assert body["detail"] == INTERNAL_ERROR_MESSAGE
    assert body["error"]["request_id"] == "req-123"
    assert response.headers["X-Request-ID"] == "req-123"


def test_request_id_generated_when_header_absent(client: TestClient) -> None:
    response = client.get("/missing")
    assert response.json()["error"]["request_id"]


def test_request_id_without_access_log_middleware_uses_header() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/x")
    async def x() -> None:
        raise HTTPException(status_code=404)

    response = TestClient(app).get("/x", headers={"X-Request-ID": "abc"})
    assert response.json()["error"]["request_id"] == "abc"
    assert TestClient(app).get("/x").json()["error"]["request_id"]


def test_code_for_registry_and_cursor_codes() -> None:
    assert code_for(400, "Invalid pagination cursor") == "INVALID_CURSOR"
    assert (
        code_for(400, "Cursor pagination requires sort_by=created_at") == "CURSOR_SORT_UNSUPPORTED"
    )
    assert code_for(599, None) == "INTERNAL_ERROR"
    assert code_for(404, {"code": "  "}) == "NOT_FOUND"
    assert code_for(200, "ok") == "ERROR"
    assert set(STATUS_ERROR_CODES.values()) >= {"VALIDATION_ERROR", "NOT_IMPLEMENTED"}
    assert all(code == code.upper() for code in DETAIL_ERROR_CODES.values())


def test_status_phrase_falls_back_for_non_http_status() -> None:
    from app.core.errors import _status_phrase

    assert _status_phrase(799) == "Error"
    assert _status_phrase(404) == "Not Found"


def test_real_app_registers_envelope() -> None:
    from app.main import app

    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["detail"] == "Not Found"
