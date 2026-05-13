from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping, MutableMapping
from typing import Any, Literal

import sentry_sdk
from sentry_sdk.types import Event, Hint

from app.core.config import Environment, settings

_logger = logging.getLogger("observability.sentry")
_initialized_runtimes: set[tuple[str, int]] = set()

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
_DOCUMENT_CONTENT_KEY_MARKERS = (
    "content",
    "text",
    "prompt",
    "question",
    "answer",
    "chunk",
    "document_body",
    "request_body",
)
_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?key|secret|token|password)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")


def _normalize_key(key: str) -> str:
    return key.lower().replace("-", "_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in _SENSITIVE_EXACT_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _is_document_content_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return any(marker in normalized for marker in _DOCUMENT_CONTENT_KEY_MARKERS)


def _redact_string(value: str) -> str:
    redacted = _INLINE_SECRET_PATTERN.sub(r"\1=***", value)
    redacted = _BEARER_TOKEN_PATTERN.sub("Bearer ***", redacted)
    return redacted


def _sanitize_value(*, key: str, value: Any) -> Any:
    if value is None:
        return None
    if _is_sensitive_key(key):
        return "***"
    if _is_document_content_key(key):
        if isinstance(value, str) and not value.strip():
            return value
        return f"<redacted:{_normalize_key(key)}>"
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, MutableMapping):
        _sanitize_mapping(value)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _sanitize_value(key=key, value=item)
        return value
    return value


def _sanitize_mapping(payload: MutableMapping[str, Any]) -> None:
    for key in list(payload.keys()):
        payload[key] = _sanitize_value(key=key, value=payload[key])


def _redact_event(event: Event) -> Event:
    request = event.get("request")
    if isinstance(request, MutableMapping):
        headers = request.get("headers")
        if isinstance(headers, MutableMapping):
            _sanitize_mapping(headers)
        if "data" in request:
            request["data"] = "<redacted:request_data>"
        _sanitize_mapping(request)

    user = event.get("user")
    if isinstance(user, MutableMapping):
        _sanitize_mapping(user)

    contexts = event.get("contexts")
    if isinstance(contexts, MutableMapping):
        _sanitize_mapping(contexts)

    tags = event.get("tags")
    if isinstance(tags, MutableMapping):
        _sanitize_mapping(tags)

    extra = event.get("extra")
    if isinstance(extra, MutableMapping):
        _sanitize_mapping(extra)

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, Mapping):
        values = breadcrumbs.get("values")
        if isinstance(values, list):
            for breadcrumb in values:
                if isinstance(breadcrumb, MutableMapping):
                    data = breadcrumb.get("data")
                    if isinstance(data, MutableMapping):
                        _sanitize_mapping(data)
                    message = breadcrumb.get("message")
                    if isinstance(message, str):
                        breadcrumb["message"] = _redact_string(message)

    message = event.get("message")
    if isinstance(message, str):
        event["message"] = _redact_string(message)

    exception = event.get("exception")
    if isinstance(exception, MutableMapping):
        _sanitize_mapping(exception)

    return event


def _before_send(event: Event, hint: Hint) -> Event | None:
    del hint
    return _redact_event(event)


def _before_breadcrumb(breadcrumb: dict[str, Any], hint: Hint) -> dict[str, Any] | None:
    del hint
    data = breadcrumb.get("data")
    if isinstance(data, MutableMapping):
        _sanitize_mapping(data)
    message = breadcrumb.get("message")
    if isinstance(message, str):
        breadcrumb["message"] = _redact_string(message)
    return breadcrumb


def resolve_sentry_sample_rates(
    *,
    environment: Environment,
    error_sample_rate: float | None,
    traces_sample_rate: float | None,
    profiles_sample_rate: float | None,
) -> tuple[float, float, float]:
    is_production_like = environment in {Environment.production, Environment.staging}
    resolved_error_sample_rate = 1.0 if error_sample_rate is None else error_sample_rate
    resolved_traces_sample_rate = (0.2 if is_production_like else 1.0) if traces_sample_rate is None else traces_sample_rate
    resolved_profiles_sample_rate = 0.0 if profiles_sample_rate is None else profiles_sample_rate
    return (
        resolved_error_sample_rate,
        resolved_traces_sample_rate,
        resolved_profiles_sample_rate,
    )


def _is_sentry_enabled() -> bool:
    client = sentry_sdk.get_client()
    return bool(getattr(client, "is_active", lambda: False)())


def init_sentry(*, runtime: Literal["api", "worker"]) -> bool:
    cache_key = (runtime, os.getpid())
    if cache_key in _initialized_runtimes:
        return _is_sentry_enabled()

    if settings.sentry_dsn is None:
        _initialized_runtimes.add(cache_key)
        _logger.info("sentry.disabled runtime=%s reason=dsn_missing", runtime)
        return False

    (
        error_sample_rate,
        traces_sample_rate,
        profiles_sample_rate,
    ) = resolve_sentry_sample_rates(
        environment=settings.environment,
        error_sample_rate=settings.sentry_error_sample_rate,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
    )

    try:
        sentry_sdk.init(
            dsn=str(settings.sentry_dsn),
            environment=settings.environment.value,
            release=settings.sentry_release or settings.api_version,
            sample_rate=error_sample_rate,
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,
            send_default_pii=False,
            include_local_variables=False,
            max_request_body_size="never",
            before_send=_before_send,
            before_breadcrumb=_before_breadcrumb,
        )
        sentry_sdk.set_tag("runtime", runtime)
    except Exception as exc:
        _initialized_runtimes.add(cache_key)
        _logger.warning(
            "sentry.disabled runtime=%s reason=init_failed error=%s",
            runtime,
            exc.__class__.__name__,
        )
        return False

    _initialized_runtimes.add(cache_key)
    _logger.info(
        "sentry.enabled runtime=%s environment=%s sample_rate=%.3f traces_sample_rate=%.3f profiles_sample_rate=%.3f",
        runtime,
        settings.environment.value,
        error_sample_rate,
        traces_sample_rate,
        profiles_sample_rate,
    )
    return True


def bind_sentry_context(
    *,
    runtime: Literal["api", "worker"],
    request_id: str | None = None,
    user_id: str | None = None,
    organization_id: str | None = None,
    task_name: str | None = None,
    task_id: str | None = None,
) -> None:
    if not _is_sentry_enabled():
        return

    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("runtime", runtime)
        scope.set_tag("request_id", request_id or "none")
        scope.set_tag("organization_id", organization_id or "none")
        if task_name is not None:
            scope.set_tag("task_name", task_name)
        if task_id is not None:
            scope.set_tag("task_id", task_id)
        scope.set_user({"id": user_id} if user_id else None)


def capture_sentry_exception(
    exc: Exception,
    *,
    runtime: Literal["api", "worker"],
    request_id: str | None = None,
    user_id: str | None = None,
    organization_id: str | None = None,
    task_name: str | None = None,
    task_id: str | None = None,
) -> str | None:
    if not _is_sentry_enabled():
        return None

    with sentry_sdk.push_scope() as scope:
        scope.set_tag("runtime", runtime)
        scope.set_tag("request_id", request_id or "none")
        scope.set_tag("organization_id", organization_id or "none")
        if task_name is not None:
            scope.set_tag("task_name", task_name)
        if task_id is not None:
            scope.set_tag("task_id", task_id)
        scope.set_user({"id": user_id} if user_id else None)
        return sentry_sdk.capture_exception(exc)


def capture_sentry_test_event(*, runtime: Literal["api", "worker"] = "api") -> str | None:
    if not _is_sentry_enabled():
        return None
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("runtime", runtime)
        scope.set_tag("event_type", "manual_test")
        return sentry_sdk.capture_message("rudix.sentry.test_event", level="info")
