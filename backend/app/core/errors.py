"""Uniform API error envelope and exception handlers (R04-10).

Body shape::

    {"error": {"code", "message", "request_id", "details"}, "detail": <legacy value>}

``detail`` is a compatibility alias that carries exactly the value the API returned
before the envelope existed; it is kept until 1.0.0. Unhandled exceptions never leak
the exception text or a traceback.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.error_codes import code_for
from app.core.logging import get_logger
from app.core.sentry import capture_sentry_exception

logger = get_logger("api.errors")

INTERNAL_ERROR_MESSAGE = "An unexpected error occurred. Please try again later."
VALIDATION_ERROR_MESSAGE = "Request validation failed"
_BODYLESS_STATUS_CODES = {204, 304}


def _request_id(request: Request) -> str:
    state_value = getattr(request.state, "request_id", None)
    if isinstance(state_value, str) and state_value:
        return state_value
    header_value = request.headers.get("x-request-id")
    if header_value:
        return header_value
    return str(uuid4())


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Error"


def _message_for(status_code: int, detail: Any) -> str:
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    return _status_phrase(status_code)


def build_error_body(
    *,
    status_code: int,
    detail: Any,
    request_id: str,
    message: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    """Build the envelope; ``detail`` is returned unchanged as the legacy alias."""
    encoded = jsonable_encoder(detail)
    return {
        "error": {
            "code": code or code_for(status_code, detail),
            "message": message or _message_for(status_code, detail),
            "request_id": request_id,
            "details": None if isinstance(encoded, str) else encoded,
        },
        "detail": encoded,
    }


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    headers = dict(exc.headers) if exc.headers else {}
    if exc.status_code in _BODYLESS_STATUS_CODES:
        return Response(status_code=exc.status_code, headers=headers)
    request_id = _request_id(request)
    headers.setdefault("X-Request-ID", request_id)
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_body(
            status_code=exc.status_code, detail=exc.detail, request_id=request_id
        ),
        headers=headers,
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    request_id = _request_id(request)
    return JSONResponse(
        status_code=422,
        content=build_error_body(
            status_code=422,
            detail=exc.errors(),
            request_id=request_id,
            message=VALIDATION_ERROR_MESSAGE,
            code="VALIDATION_ERROR",
        ),
        headers={"X-Request-ID": request_id},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    principal = getattr(request.state, "auth_principal", None)
    user_id = getattr(principal, "user_id", None)
    organization_id = getattr(principal, "organization_id", None)
    logger.error(
        "api.error.unhandled",
        request_id=request_id,
        endpoint=request.url.path,
        method=request.method,
        error=exc.__class__.__name__,
        exc_info=exc,
    )
    capture_sentry_exception(
        exc,
        runtime="api",
        request_id=request_id,
        user_id=str(user_id) if user_id else None,
        organization_id=str(organization_id) if organization_id else None,
    )
    return JSONResponse(
        status_code=500,
        content=build_error_body(
            status_code=500,
            detail=INTERNAL_ERROR_MESSAGE,
            request_id=request_id,
        ),
        headers={"X-Request-ID": request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
