from __future__ import annotations

import logging
import re
import sys
from time import perf_counter
from typing import Any, Literal, cast
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from structlog.types import EventDict

from app.core.sentry import bind_sentry_context, capture_sentry_exception

LOG_FORMAT_AUTO = "auto"
LOG_FORMAT_JSON = "json"
LOG_FORMAT_CONSOLE = "console"
ResolvedLogFormat = Literal["json", "console"]

_HANDLER_MARKER = "_rudix_structured_handler"

_SENSITIVE_EXACT_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "authorization",
    "cookie",
    "set_cookie",
    "access_key",
    "secret_key",
}
_SENSITIVE_SUFFIXES = (
    "_password",
    "_secret",
    "_token",
    "_api_key",
    "_authorization",
    "_cookie",
    "_access_key",
    "_secret_key",
)
_SENSITIVE_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|password)\b\s*[:=]\s*([^\s,;]+)"
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _SENSITIVE_EXACT_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _redact_sensitive_fields(_: Any, __: str, event_dict: EventDict) -> EventDict:
    for key, value in list(event_dict.items()):
        if value is None:
            continue
        if _is_sensitive_key(key):
            event_dict[key] = "***"
            continue
        if isinstance(value, str):
            event_dict[key] = _SENSITIVE_PATTERN.sub(r"\1=***", value)
    return event_dict


def _resolve_log_format(environment: str, log_format: str) -> ResolvedLogFormat:
    normalized = log_format.strip().lower()
    if normalized == LOG_FORMAT_JSON:
        return "json"
    if normalized == LOG_FORMAT_CONSOLE:
        return "console"
    if normalized != LOG_FORMAT_AUTO:
        raise ValueError(f"Unsupported log format: {log_format}")
    if environment.lower() in {"production", "staging"}:
        return "json"
    return "console"


def configure_logging(
    level: str = "INFO",
    *,
    environment: str = "development",
    log_format: str = LOG_FORMAT_AUTO,
) -> None:
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    resolved_format = _resolve_log_format(environment=environment, log_format=log_format)

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)

    existing_handlers = [
        handler for handler in root_logger.handlers if getattr(handler, _HANDLER_MARKER, False)
    ]
    if not existing_handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(resolved_level)
        setattr(handler, _HANDLER_MARKER, True)
        root_logger.addHandler(handler)
    else:
        for existing_handler in existing_handlers:
            existing_handler.setLevel(resolved_level)

    renderer: Any
    if resolved_format == LOG_FORMAT_JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_sensitive_fields,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _redact_sensitive_fields,
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def _pick_context_from_request(request: Request) -> dict[str, str | None]:
    path_params = request.path_params or {}
    headers = request.headers
    principal = getattr(request.state, "auth_principal", None)
    principal_user_id = getattr(principal, "user_id", None)
    principal_organization_id = getattr(principal, "organization_id", None)
    return {
        "request_id": headers.get("x-request-id"),
        "user_id": principal_user_id or headers.get("x-user-id"),
        "organization_id": principal_organization_id or headers.get("x-organization-id"),
        "document_id": path_params.get("document_id") or headers.get("x-document-id"),
        "job_id": path_params.get("evaluation_run_id") or headers.get("x-job-id"),
    }


def attach_access_log_middleware(app: FastAPI) -> None:
    access_logger = get_logger("api.access")
    exception_logger = get_logger("api.exception")

    @app.middleware("http")
    async def structured_access_log_middleware(request: Request, call_next: Any) -> Any:
        started_at = perf_counter()
        context = _pick_context_from_request(request)
        request_id = context["request_id"] or str(uuid4())
        context["request_id"] = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(**context)
        bind_sentry_context(
            runtime="api",
            request_id=request_id,
            user_id=context["user_id"],
            organization_id=context["organization_id"],
        )

        response = None
        status_code = 500
        error_message: str | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            error_message = exc.__class__.__name__
            exception_logger.exception(
                "api.exception.unhandled",
                endpoint=request.url.path,
                method=request.method,
                error=error_message,
            )
            capture_sentry_exception(
                exc,
                runtime="api",
                request_id=request_id,
                user_id=context["user_id"],
                organization_id=context["organization_id"],
            )
            raise
        finally:
            latency_ms = round((perf_counter() - started_at) * 1000, 2)
            log_context = _pick_context_from_request(request)
            log_context["request_id"] = request_id
            bind_sentry_context(
                runtime="api",
                request_id=request_id,
                user_id=log_context["user_id"],
                organization_id=log_context["organization_id"],
            )
            access_logger.info(
                "api.request",
                request_id=log_context["request_id"],
                user_id=log_context["user_id"],
                organization_id=log_context["organization_id"],
                document_id=log_context["document_id"],
                job_id=log_context["job_id"],
                endpoint=request.url.path,
                method=request.method,
                status_code=status_code,
                latency_ms=latency_ms,
                error=error_message,
            )
            structlog.contextvars.clear_contextvars()
            if response is not None:
                response.headers.setdefault("X-Request-ID", request_id)


def log_document_event(
    *,
    event: str,
    document_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    job_id: str | None = None,
    **fields: Any,
) -> None:
    get_logger("events.document").info(
        event,
        user_id=user_id,
        organization_id=organization_id,
        document_id=document_id,
        job_id=job_id,
        **fields,
    )


def log_query_event(
    *,
    event: str,
    organization_id: str | None = None,
    user_id: str | None = None,
    job_id: str | None = None,
    **fields: Any,
) -> None:
    get_logger("events.query").info(
        event,
        organization_id=organization_id,
        user_id=user_id,
        job_id=job_id,
        **fields,
    )


def log_evaluation_event(
    *,
    event: str,
    organization_id: str | None = None,
    user_id: str | None = None,
    job_id: str | None = None,
    **fields: Any,
) -> None:
    get_logger("events.evaluation").info(
        event,
        organization_id=organization_id,
        user_id=user_id,
        job_id=job_id,
        **fields,
    )


def log_task_failure(
    *,
    task_name: str,
    job_id: str | None = None,
    document_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    error: str | None = None,
    exc_info: bool = True,
    **fields: Any,
) -> None:
    get_logger("events.task").error(
        "task.failure",
        task_name=task_name,
        job_id=job_id,
        document_id=document_id,
        organization_id=organization_id,
        user_id=user_id,
        error=error,
        exc_info=exc_info,
        **fields,
    )
