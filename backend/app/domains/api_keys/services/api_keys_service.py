from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from app.models.api_key import ApiKey
from app.domains.api_keys.schemas.api_keys import ApiKeyCreatedResponse, ApiKeyResponse
from app.models.permissions import PermissionType

_KEY_PREFIX = "rudix_"
_KEY_RANDOM_BYTES = 32
_PREFIX_DISPLAY_LENGTH = 16

SCOPE_TO_PERMISSIONS: dict[str, frozenset[str]] = {
    "documents:read": frozenset({PermissionType.documents_view}),
    "documents:write": frozenset({
        PermissionType.documents_view,
        PermissionType.documents_upload,
        PermissionType.documents_delete,
        PermissionType.documents_manage,
    }),
    "chat:write": frozenset({
        PermissionType.chat_use,
        PermissionType.chat_use_collections,
        PermissionType.chat_manage_sessions,
    }),
    "evaluations:run": frozenset({
        PermissionType.evaluations_view,
        PermissionType.evaluations_create,
        PermissionType.evaluations_run,
    }),
    "webhooks:manage": frozenset({
        PermissionType.webhooks_list,
        PermissionType.webhooks_create,
        PermissionType.webhooks_delete,
    }),
    "connectors:manage": frozenset(),
}


class ApiKeysService:
    @staticmethod
    def generate_raw_key() -> str:
        random_part = secrets.token_urlsafe(_KEY_RANDOM_BYTES)
        return f"{_KEY_PREFIX}{random_part}"

    @staticmethod
    def hash_key(raw_key: str) -> str:
        return hashlib.sha256(raw_key.encode()).hexdigest()

    @staticmethod
    def key_prefix(raw_key: str) -> str:
        return raw_key[:_PREFIX_DISPLAY_LENGTH]

    @staticmethod
    def is_expired(api_key: ApiKey) -> bool:
        if api_key.expires_at is None:
            return False
        return datetime.now(tz=timezone.utc) > api_key.expires_at.replace(
            tzinfo=timezone.utc
        )

    @staticmethod
    def scopes_to_permissions(scopes: list[str]) -> frozenset[str]:
        perms: set[str] = set()
        for scope in scopes:
            perms.update(SCOPE_TO_PERMISSIONS.get(scope, frozenset()))
        return frozenset(perms)

    @staticmethod
    def to_api_key_response(key: ApiKey) -> ApiKeyResponse:
        return ApiKeyResponse(
            id=str(key.id),
            organization_id=str(key.organization_id),
            name=key.name,
            description=key.description,
            key_prefix=key.key_prefix,
            scopes=key.scopes if isinstance(key.scopes, list) else [],
            status=key.status,
            expires_at=key.expires_at,
            last_used_at=key.last_used_at,
            created_by_id=str(key.created_by_id) if key.created_by_id else None,
            created_at=key.created_at,
            updated_at=key.updated_at,
        )

    @classmethod
    def to_api_key_created_response(
        cls, key: ApiKey, raw_key: str
    ) -> ApiKeyCreatedResponse:
        base = cls.to_api_key_response(key)
        return ApiKeyCreatedResponse(**base.model_dump(), raw_key=raw_key)
