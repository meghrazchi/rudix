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
    "access_token",
    "api_token",
    "password",
    "private_key",
    "refresh_token",
    "id_token",
    "client_secret",
    "secret",
    "token",
    "api_key",
    "x_api_key",
    "authorization",
    "authorization_header",
    "cookie",
    "set_cookie",
    "access_key",
    "secret_key",
    "service_account_key",
}
_SENSITIVE_SUFFIXES = (
    "_access_token",
    "_api_token",
    "_client_secret",
    "_id_token",
    "_password",
    "_private_key",
    "_refresh_token",
    "_secret",
    "_token",
    "_api_key",
    "_x_api_key",
    "_authorization",
    "_authorization_header",
    "_cookie",
    "_access_key",
    "_secret_key",
    "_service_account_key",
)
_SENSITIVE_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|x[_-]?api[_-]?key|access[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|private[_-]?key|secret|token|password)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_AUTHORIZATION_HEADER_PATTERN = re.compile(
    r"(?i)\b(authorization|x-api-key)\b\s*[:=]\s*([^\s,;]+(?:\s+[^\s,;]+)?)"
)


def _is_sensitive_key(key: str) -> bool:
    snake_case = re.sub(r"(?<!^)(?=[A-Z])", "_", key)
    normalized = snake_case.lower().replace("-", "_")
    return normalized in _SENSITIVE_EXACT_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _redact_sensitive_fields(_: Any, __: str, event_dict: EventDict) -> EventDict:
    for key, value in list(event_dict.items()):
        if value is None:
            continue
        if _is_sensitive_key(key):
            event_dict[key] = "***"
            continue
        if isinstance(value, str):
            redacted = _SENSITIVE_PATTERN.sub(r"\1=***", value)
            redacted = _BEARER_TOKEN_PATTERN.sub("Bearer ***", redacted)
            event_dict[key] = _AUTHORIZATION_HEADER_PATTERN.sub(r"\1=***", redacted)
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
        request.state.request_id = request_id

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


def log_connector_event(
    *,
    event: str,
    provider_key: str | None = None,
    connection_id: str | None = None,
    external_source_id: str | None = None,
    external_item_id: str | None = None,
    sync_run_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    **fields: Any,
) -> None:
    get_logger("events.connector").info(
        event,
        user_id=user_id,
        organization_id=organization_id,
        provider_key=provider_key,
        connection_id=connection_id,
        external_source_id=external_source_id,
        external_item_id=external_item_id,
        sync_run_id=sync_run_id,
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


def log_agent_event(
    *,
    event: str,
    organization_id: str | None = None,
    user_id: str | None = None,
    run_id: str | None = None,
    tool_name: str | None = None,
    **fields: Any,
) -> None:
    get_logger("events.agent").info(
        event,
        organization_id=organization_id,
        user_id=user_id,
        run_id=run_id,
        tool_name=tool_name,
        **fields,
    )


def log_authorization_event(
    *,
    event: str,
    organization_id: str | None = None,
    user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    deny_reason: str | None = None,
    matched_rule: str | None = None,
    request_id: str | None = None,
    **fields: Any,
) -> None:
    get_logger("events.authorization").info(
        event,
        organization_id=organization_id,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        decision=decision,
        deny_reason=deny_reason,
        matched_rule=matched_rule,
        request_id=request_id,
        **fields,
    )


def log_chunking_event(
    *,
    event: str,
    document_id: str | None = None,
    organization_id: str | None = None,
    user_id: str | None = None,
    strategy: str | None = None,
    chunk_count: int | None = None,
    avg_tokens: float | None = None,
    max_tokens: int | None = None,
    min_tokens: int | None = None,
    duration_ms: int | None = None,
    profile_source: str | None = None,
    reason_codes: list[str] | None = None,
    empty_pages: int | None = None,
    language: str | None = None,
    **fields: Any,
) -> None:
    get_logger("events.chunking").info(
        event,
        document_id=document_id,
        organization_id=organization_id,
        user_id=user_id,
        strategy=strategy,
        chunk_count=chunk_count,
        avg_tokens=avg_tokens,
        max_tokens=max_tokens,
        min_tokens=min_tokens,
        duration_ms=duration_ms,
        profile_source=profile_source,
        reason_codes=reason_codes,
        empty_pages=empty_pages,
        language=language,
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
