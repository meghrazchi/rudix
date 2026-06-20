from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from app.domains.api_keys.services.api_keys_service import SCOPE_TO_PERMISSIONS
from app.domains.service_accounts.schemas.service_accounts import (
    ServiceAccountResponse,
    ServiceAccountTokenCreatedResponse,
    ServiceAccountTokenResponse,
)
from app.models.service_account import ServiceAccount, ServiceAccountToken

_TOKEN_PREFIX = "svc_"
_TOKEN_RANDOM_BYTES = 32
_PREFIX_DISPLAY_LENGTH = 16


class ServiceAccountsService:
    @staticmethod
    def generate_raw_token() -> str:
        random_part = secrets.token_urlsafe(_TOKEN_RANDOM_BYTES)
        return f"{_TOKEN_PREFIX}{random_part}"

    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode()).hexdigest()

    @staticmethod
    def token_prefix(raw_token: str) -> str:
        return raw_token[:_PREFIX_DISPLAY_LENGTH]

    @staticmethod
    def is_expired(token: ServiceAccountToken) -> bool:
        if token.expires_at is None:
            return False
        return datetime.now(tz=UTC) > token.expires_at.replace(tzinfo=UTC)

    @staticmethod
    def scopes_to_permissions(scopes: list[str]) -> frozenset[str]:
        perms: set[str] = set()
        for scope in scopes:
            perms.update(SCOPE_TO_PERMISSIONS.get(scope, frozenset()))
        return frozenset(perms)

    @staticmethod
    def to_service_account_response(account: ServiceAccount) -> ServiceAccountResponse:
        return ServiceAccountResponse(
            id=str(account.id),
            organization_id=str(account.organization_id),
            name=account.name,
            description=account.description,
            environment=account.environment,
            scopes=account.scopes if isinstance(account.scopes, list) else [],
            is_active=account.is_active,
            last_used_at=account.last_used_at,
            created_by_id=str(account.created_by_id) if account.created_by_id else None,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    @staticmethod
    def to_token_response(token: ServiceAccountToken) -> ServiceAccountTokenResponse:
        return ServiceAccountTokenResponse(
            id=str(token.id),
            service_account_id=str(token.service_account_id),
            name=token.name,
            token_prefix=token.token_prefix,
            status=token.status,
            expires_at=token.expires_at,
            last_used_at=token.last_used_at,
            created_by_id=str(token.created_by_id) if token.created_by_id else None,
            created_at=token.created_at,
            updated_at=token.updated_at,
        )

    @classmethod
    def to_token_created_response(
        cls, token: ServiceAccountToken, raw_token: str
    ) -> ServiceAccountTokenCreatedResponse:
        base = cls.to_token_response(token)
        return ServiceAccountTokenCreatedResponse(**base.model_dump(), raw_token=raw_token)
