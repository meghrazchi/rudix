from __future__ import annotations

from typing import Any

import httpx

from app.core.config import ConnectorOAuthClientSettings, settings
from app.domains.connectors.schemas.credentials import OAuthTokenResponse
from app.domains.connectors.services.oauth_lifecycle import OAuthLifecycleError
from app.domains.connectors.services.provider_registry import (
    ProviderRegistry,
    default_provider_registry,
)


class HttpOAuthTokenClient:
    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry | None = None,
        client_settings: list[ConnectorOAuthClientSettings] | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.provider_registry = provider_registry or default_provider_registry
        self.client_settings = (
            client_settings
            if client_settings is not None
            else list(settings.connector_oauth_clients)
        )
        self.timeout_seconds = timeout_seconds or settings.dependency_read_timeout_seconds

    async def exchange_code(
        self,
        *,
        provider_key: str,
        code: str,
        redirect_uri: str,
        scopes: list[str],
    ) -> OAuthTokenResponse:
        client_config = self._require_client(provider_key)
        provider = self.provider_registry.require(provider_key)
        if provider.oauth is None:
            raise OAuthLifecycleError("connector provider does not support OAuth")
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_config.client_id,
            "client_secret": client_config.client_secret.get_secret_value(),
        }
        return await self._post_token(provider.oauth.token_endpoint, payload)

    async def refresh(
        self,
        *,
        provider_key: str,
        refresh_token: str,
        scopes: list[str],
    ) -> OAuthTokenResponse:
        client_config = self._require_client(provider_key)
        provider = self.provider_registry.require(provider_key)
        if provider.oauth is None:
            raise OAuthLifecycleError("connector provider does not support OAuth")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_config.client_id,
            "client_secret": client_config.client_secret.get_secret_value(),
        }
        if scopes:
            payload["scope"] = " ".join(scopes)
        return await self._post_token(provider.oauth.token_endpoint, payload)

    async def revoke(
        self,
        *,
        provider_key: str,
        token: str,
        token_type_hint: str,
    ) -> None:
        client_config = self._require_client(provider_key)
        provider = self.provider_registry.require(provider_key)
        if provider.oauth is None or provider.oauth.revoke_endpoint is None:
            return
        payload = {
            "token": token,
            "token_type_hint": token_type_hint,
            "client_id": client_config.client_id,
            "client_secret": client_config.client_secret.get_secret_value(),
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(provider.oauth.revoke_endpoint, data=payload)
            # Revocation is best-effort: 4xx means the token is already invalid/expired,
            # which is fine. Only surface 5xx server errors.
            if response.is_server_error:
                response.raise_for_status()

    def _require_client(self, provider_key: str) -> ConnectorOAuthClientSettings:
        normalized_provider_key = provider_key.strip().lower()
        for client_config in self.client_settings:
            if client_config.provider_key == normalized_provider_key:
                return client_config
        raise OAuthLifecycleError("connector OAuth client is not configured")

    async def _post_token(self, token_endpoint: str, payload: dict[str, Any]) -> OAuthTokenResponse:
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(token_endpoint, data=payload)
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise OAuthLifecycleError("OAuth token endpoint returned an invalid payload")
        return OAuthTokenResponse.model_validate(data)
