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
    # Neo4j credentials (F290)
    "neo4j_password",
    "neo4j_auth",
    "bolt_password",
    "neo4j_uri",
    "bolt_uri",
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
    # Neo4j credentials (F290)
    "_neo4j_password",
    "_bolt_password",
    "_neo4j_auth",
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
    r"(?i)\b(api[_-]?key|x[_-]?api[_-]?key|access[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|private[_-]?key|secret|token|password)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_AUTHORIZATION_HEADER_PATTERN = re.compile(
    r"(?i)\b(authorization|x-api-key)\b\s*[:=]\s*([^\s,;]+(?:\s+[^\s,;]+)?)"
)


def _normalize_key(key: str) -> str:
    snake_case = re.sub(r"(?<!^)(?=[A-Z])", "_", key)
    return snake_case.lower().replace("-", "_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in _SENSITIVE_EXACT_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _is_content_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in _CONTENT_EXACT_KEYS or normalized.endswith(_CONTENT_SUFFIXES)


def _redact_string(value: str) -> str:
    redacted = _INLINE_SECRET_PATTERN.sub(r"\1=***", value)
    redacted = _BEARER_TOKEN_PATTERN.sub("Bearer ***", redacted)
    redacted = _AUTHORIZATION_HEADER_PATTERN.sub(r"\1=***", redacted)
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
