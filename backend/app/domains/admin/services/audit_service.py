from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.admin.repositories.usage import UsageRepository

_logger = get_logger("services.audit")

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
_CONTENT_EXACT_KEYS = {
    "content",
    "text",
    "prompt",
    "question",
    "answer",
    "document_body",
    "request_body",
}
_CONTENT_SUFFIXES = (
    "_content",
    "_text",
    "_prompt",
    "_question",
    "_answer",
    "_document_body",
    "_request_body",
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


def _is_content_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in _CONTENT_EXACT_KEYS or normalized.endswith(_CONTENT_SUFFIXES)


def _redact_string(value: str) -> str:
    redacted = _INLINE_SECRET_PATTERN.sub(r"\1=***", value)
    redacted = _BEARER_TOKEN_PATTERN.sub("Bearer ***", redacted)
    return redacted


def _sanitize_value(*, key: str, value: Any) -> Any:
    if value is None:
        return None
    if _is_sensitive_key(key):
        return "***"
    if _is_content_key(key):
        if isinstance(value, str) and not value.strip():
            return value
        return f"<redacted:{_normalize_key(key)}>"
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, MutableMapping):
        return sanitize_metadata(value)
    if isinstance(value, list):
        return [_sanitize_value(key=key, value=item) for item in value]
    return value


def sanitize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    return {str(key): _sanitize_value(key=str(key), value=value) for key, value in metadata.items()}


def _parse_resource_id(resource_id: UUID | str | None) -> UUID | None:
    if resource_id is None:
        return None
    if isinstance(resource_id, UUID):
        return resource_id
    try:
        return UUID(resource_id)
    except ValueError:
        return None


class AuditLogService:
    def __init__(self, usage_repository: UsageRepository | None = None) -> None:
        self._usage_repository = usage_repository or UsageRepository()

    async def record(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | str | None = None,
        request_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        required: bool = False,
    ) -> bool:
        audit_metadata = sanitize_metadata(metadata)
        if request_id:
            audit_metadata["request_id"] = request_id
        raw_resource_id = resource_id if isinstance(resource_id, str) else None
        if raw_resource_id and "resource_id_raw" not in audit_metadata:
            audit_metadata["resource_id_raw"] = raw_resource_id

        parsed_resource_id = _parse_resource_id(resource_id)
        try:
            await self._usage_repository.create_audit_log(
                session,
                organization_id=organization_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=parsed_resource_id,
                metadata=audit_metadata,
            )
            return True
        except Exception as exc:
            _logger.warning(
                "audit.log.write_failed",
                action=action,
                resource_type=resource_type,
                organization_id=str(organization_id),
                user_id=str(user_id) if user_id is not None else None,
                request_id=request_id,
                error=exc.__class__.__name__,
            )
            if required:
                raise
            return False
