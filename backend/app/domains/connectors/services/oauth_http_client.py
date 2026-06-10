from __future__ import annotations

import base64
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
        del scopes
        client_config = self._require_client(provider_key)
        provider = self.provider_registry.require(provider_key)
        if provider.oauth is None:
            raise OAuthLifecycleError("connector provider does not support OAuth")
        use_basic_auth = provider.oauth.token_endpoint_auth_method == "client_secret_basic"
        payload: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if not use_basic_auth:
            payload["client_id"] = client_config.client_id or ""
            payload["client_secret"] = client_config.client_secret.get_secret_value()
        return await self._post_token(
            provider.oauth.token_endpoint,
            payload,
            basic_auth=_basic_auth_header(client_config) if use_basic_auth else None,
        )

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
        use_basic_auth = provider.oauth.token_endpoint_auth_method == "client_secret_basic"
        payload: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        if not use_basic_auth:
            payload["client_id"] = client_config.client_id or ""
            payload["client_secret"] = client_config.client_secret.get_secret_value()
        if scopes:
            payload["scope"] = " ".join(scopes)
        return await self._post_token(
            provider.oauth.token_endpoint,
            payload,
            basic_auth=_basic_auth_header(client_config) if use_basic_auth else None,
        )

    async def fetch_accessible_resources(
        self,
        *,
        access_token: str,
        endpoint: str,
    ) -> list[dict]:
        """Fetch the list of accessible cloud resources for a given access token.

        Used by Atlassian (Confluence/Jira) to resolve the cloud_id after token exchange.
        Returns a list of resource dicts, each containing at minimum "id" and "url".
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.get(endpoint, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise OAuthLifecycleError(
                    f"accessible-resources endpoint returned HTTP {exc.response.status_code}"
                ) from exc
            except httpx.RequestError as exc:
                raise OAuthLifecycleError(
                    "accessible-resources endpoint is unreachable"
                ) from exc
        data = response.json()
        if not isinstance(data, list):
            raise OAuthLifecycleError(
                "accessible-resources endpoint returned an unexpected payload"
            )
        return data

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

    async def _post_token(
        self,
        token_endpoint: str,
        payload: dict[str, Any],
        *,
        basic_auth: str | None = None,
    ) -> OAuthTokenResponse:
        headers = {"Authorization": f"Basic {basic_auth}"} if basic_auth else {}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.post(token_endpoint, data=payload, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                provider_error = (
                    _extract_provider_error_code(exc.response) if exc.response else None
                )
                if status_code is None:
                    raise OAuthLifecycleError("OAuth token endpoint rejected the request") from exc
                if provider_error is not None:
                    raise OAuthLifecycleError(
                        f"OAuth token endpoint rejected the request (HTTP {status_code}: {provider_error})"
                    ) from exc
                raise OAuthLifecycleError(
                    f"OAuth token endpoint rejected the request (HTTP {status_code})"
                ) from exc
            except httpx.RequestError as exc:
                raise OAuthLifecycleError("OAuth token endpoint is unreachable") from exc
            data = response.json()
        if not isinstance(data, dict):
            raise OAuthLifecycleError("OAuth token endpoint returned an invalid payload")
        return OAuthTokenResponse.model_validate(data)


def _basic_auth_header(client_config: ConnectorOAuthClientSettings) -> str:
    raw = f"{client_config.client_id or ''}:{client_config.client_secret.get_secret_value()}"
    return base64.b64encode(raw.encode()).decode()


def _extract_provider_error_code(response: httpx.Response | None) -> str | None:
    if response is None:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if not isinstance(error, str):
        return None
    cleaned = error.strip()
    return cleaned or None
