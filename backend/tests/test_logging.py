import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging import _HANDLER_MARKER, attach_access_log_middleware, configure_logging


def _clear_rudix_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)


def test_configure_logging_does_not_duplicate_handlers() -> None:
    _clear_rudix_handlers()

    configure_logging("INFO", environment="test", log_format="json")
    first_count = sum(1 for handler in logging.getLogger().handlers if getattr(handler, _HANDLER_MARKER, False))

    configure_logging("DEBUG", environment="test", log_format="json")
    second_count = sum(1 for handler in logging.getLogger().handlers if getattr(handler, _HANDLER_MARKER, False))

    assert first_count == 1
    assert second_count == 1


def test_access_log_contains_request_id_and_latency(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO", environment="test", log_format="json")

    app = FastAPI()
    attach_access_log_middleware(app)

    @app.get("/documents/{document_id}")
    async def read_document(document_id: str) -> dict[str, str]:
        return {"document_id": document_id}

    client = TestClient(app)
    caplog.set_level(logging.INFO)

    response = client.get(
        "/documents/doc_123",
        headers={
            "x-request-id": "req_123",
            "x-user-id": "user_1",
            "x-organization-id": "org_1",
            "x-job-id": "job_1",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req_123"

    access_logs = [record for record in caplog.records if record.name == "api.access"]
    assert len(access_logs) == 1

    payload = json.loads(access_logs[0].getMessage())
    assert payload["event"] == "api.request"
    assert payload["request_id"] == "req_123"
    assert payload["user_id"] == "user_1"
    assert payload["organization_id"] == "org_1"
    assert payload["document_id"] == "doc_123"
    assert payload["job_id"] == "job_1"
    assert payload["endpoint"] == "/documents/doc_123"
    assert payload["status_code"] == 200
    assert isinstance(payload["latency_ms"], (int, float))


def test_exception_log_contains_traceback_and_masks_secrets(caplog: pytest.LogCaptureFixture) -> None:
    configure_logging("INFO", environment="test", log_format="json")

    app = FastAPI()
    attach_access_log_middleware(app)

    @app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("password=supersecret")

    client = TestClient(app, raise_server_exceptions=False)
    caplog.set_level(logging.INFO)

    response = client.get("/boom")

    assert response.status_code == 500

    exception_logs = [record for record in caplog.records if record.name == "api.exception"]
    assert len(exception_logs) == 1

    payload = json.loads(exception_logs[0].getMessage())
    assert payload["event"] == "api.exception.unhandled"
    assert "Traceback" in payload["exception"]
    assert "supersecret" not in payload["exception"]
