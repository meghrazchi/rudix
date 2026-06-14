from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.bots.repositories.bots import BotRepository
from app.domains.bots.services.credential_vault import BotCredentialVault
from app.models.bot import BotInstallation

_SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
_SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
_STATE_VERSION = 1


class BotOAuthError(ValueError):
    """Safe OAuth lifecycle error for collaboration bots."""


@dataclass(frozen=True)
class BotSlackOAuthStart:
    authorization_url: str
    state: str
    redirect_uri: str
    scopes: list[str]
    expires_in_seconds: int


@dataclass(frozen=True)
class BotSlackOAuthCallback:
    installation: BotInstallation


class BotSlackOAuthService:
    def __init__(
        self,
        *,
        repository: BotRepository | None = None,
        credential_vault: BotCredentialVault | None = None,
        audit_service: AuditLogService | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._repository = repository or BotRepository()
        self._credential_vault = credential_vault or BotCredentialVault()
        self._audit_service = audit_service or AuditLogService()
        self._timeout_seconds = timeout_seconds or settings.dependency_read_timeout_seconds

    async def begin_install(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        request_id: str | None = None,
        scopes: list[str] | None = None,
        redirect_uri: str | None = None,
    ) -> BotSlackOAuthStart:
        client_id = _require_slack_client_id()
        resolved_scopes = _normalize_scopes(scopes or _configured_slack_scopes())
        resolved_redirect_uri = redirect_uri or _default_slack_redirect_uri()
        ttl_seconds = settings.connector_oauth_state_ttl_seconds
        state = _encode_state(
            {
                "version": _STATE_VERSION,
                "provider": "slack",
                "organization_id": str(organization_id),
                "user_id": str(user_id),
                "redirect_uri": resolved_redirect_uri,
                "scopes": resolved_scopes,
                "nonce": secrets.token_urlsafe(16),
                "exp": int((datetime.now(tz=UTC) + timedelta(seconds=ttl_seconds)).timestamp()),
            }
        )
        await self._audit_service.record(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action="bots.slack.oauth.started",
            resource_type="bot_installation",
            request_id=request_id,
            metadata={
                "provider": "slack",
                "scopes": resolved_scopes,
                "redirect_uri": resolved_redirect_uri,
            },
        )
        return BotSlackOAuthStart(
            authorization_url=_authorization_url(
                client_id=client_id,
                redirect_uri=resolved_redirect_uri,
                scopes=resolved_scopes,
                state=state,
            ),
            state=state,
            redirect_uri=resolved_redirect_uri,
            scopes=resolved_scopes,
            expires_in_seconds=ttl_seconds,
        )

    async def complete_install(
        self,
        session: AsyncSession,
        *,
        state: str,
        code: str | None,
        error: str | None = None,
        request_id: str | None = None,
    ) -> BotSlackOAuthCallback:
        state_payload = _decode_state(state)
        if state_payload.get("provider") != "slack":
            raise BotOAuthError("Invalid Slack OAuth state")
        if error:
            raise BotOAuthError("Slack OAuth authorization was cancelled or rejected")
        if not code or not code.strip():
            raise BotOAuthError("Slack OAuth callback code is required")

        try:
            organization_id = UUID(str(state_payload["organization_id"]))
            user_id = UUID(str(state_payload["user_id"]))
        except (KeyError, ValueError) as exc:
            raise BotOAuthError("Invalid Slack OAuth state") from exc
        redirect_uri = str(state_payload.get("redirect_uri") or "").strip()
        if not redirect_uri:
            raise BotOAuthError("Invalid Slack OAuth state")
        requested_scopes = _normalize_scopes(list(state_payload.get("scopes") or []))
        token_payload = await self._exchange_code(code=code.strip(), redirect_uri=redirect_uri)

        access_token = _require_string(token_payload, "access_token")
        team = _as_dict(token_payload.get("team"))
        enterprise = _as_dict(token_payload.get("enterprise"))
        external_workspace_id = _require_string(team, "id")
        external_tenant_id = str(enterprise.get("id") or "").strip()
        scopes = _normalize_scopes(_split_scopes(str(token_payload.get("scope") or "")))
        if not scopes:
            scopes = requested_scopes

        existing = await self._repository.get_installation_by_external_scope(
            session,
            provider="slack",
            external_workspace_id=external_workspace_id,
            external_tenant_id=external_tenant_id,
            external_team_id="",
        )
        if existing is not None and existing.organization_id != organization_id:
            raise BotOAuthError("Slack workspace is already connected to another organization")

        safe_config = {
            "oauth": {
                "team_name": str(team.get("name") or "").strip() or None,
                "enterprise_name": str(enterprise.get("name") or "").strip() or None,
                "bot_user_id": str(token_payload.get("bot_user_id") or "").strip() or None,
                "app_id": str(token_payload.get("app_id") or "").strip() or None,
                "installed_via": "slack_oauth_v2",
            }
        }
        if existing is None:
            installation = await self._repository.create_installation(
                session,
                organization_id=organization_id,
                provider="slack",
                external_workspace_id=external_workspace_id,
                external_tenant_id=external_tenant_id,
                external_team_id="",
                display_name=str(team.get("name") or "Rudix Slack"),
                status="enabled",
                default_source_scope={},
                config=safe_config,
                installed_by_user_id=user_id,
            )
            audit_action = "bots.installation.created"
        else:
            installation = await self._repository.update_installation(
                session,
                installation=existing,
                display_name=str(team.get("name") or existing.display_name or "Rudix Slack"),
                status="enabled",
                config=safe_config,
            )
            audit_action = "bots.installation.updated"

        installation = await self._credential_vault.store_bot_token(
            session,
            installation=installation,
            bot_token=access_token,
            scopes=scopes,
        )
        await self._audit_service.record(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=audit_action,
            resource_type="bot_installation",
            resource_id=installation.id,
            request_id=request_id,
            metadata={
                "provider": "slack",
                "external_workspace_id": installation.external_workspace_id,
                "external_tenant_id": installation.external_tenant_id,
                "credential_fingerprint": installation.bot_token_fingerprint,
                "scopes": scopes,
                "oauth": True,
            },
        )
        return BotSlackOAuthCallback(installation=installation)

    async def _exchange_code(self, *, code: str, redirect_uri: str) -> dict[str, Any]:
        client_id = _require_slack_client_id()
        client_secret = _require_slack_client_secret()
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                response = await client.post(_SLACK_TOKEN_URL, data=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response else "unknown"
                raise BotOAuthError(
                    f"Slack OAuth token exchange failed (HTTP {status_code})"
                ) from exc
            except httpx.RequestError as exc:
                raise BotOAuthError("Slack OAuth token endpoint is unreachable") from exc
        data = response.json()
        if not isinstance(data, dict):
            raise BotOAuthError("Slack OAuth token endpoint returned an invalid payload")
        if data.get("ok") is not True:
            raise BotOAuthError("Slack OAuth token exchange was rejected")
        return data


def _authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "scope": ",".join(scopes),
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{_SLACK_AUTHORIZE_URL}?{query}"


def _default_slack_redirect_uri() -> str:
    if settings.bot_slack_oauth_redirect_uri is not None:
        return str(settings.bot_slack_oauth_redirect_uri)
    api_base = str(settings.api_base_url).rstrip("/")
    prefix = settings.api_prefix.rstrip("/")
    return f"{api_base}{prefix}/bots/slack/oauth/callback"


def _configured_slack_scopes() -> list[str]:
    return _normalize_scopes(_split_scopes(settings.bot_slack_oauth_scopes))


def _split_scopes(value: str) -> list[str]:
    if not value:
        return []
    raw = value.replace(",", " ").split()
    return [item.strip() for item in raw if item.strip()]


def _normalize_scopes(scopes: list[str]) -> list[str]:
    normalized: list[str] = []
    for scope in scopes:
        cleaned = str(scope).strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _require_slack_client_id() -> str:
    client_id = settings.bot_slack_client_id
    if not client_id or not client_id.strip():
        raise BotOAuthError("Slack OAuth client ID is not configured")
    return client_id.strip()


def _require_slack_client_secret() -> str:
    secret = settings.bot_slack_client_secret
    if secret is None or not secret.get_secret_value().strip():
        raise BotOAuthError("Slack OAuth client secret is not configured")
    return secret.get_secret_value().strip()


def _encode_state(payload: dict[str, Any]) -> str:
    encoded_payload = _b64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    )
    signature = _sign(encoded_payload)
    return f"{encoded_payload}.{signature}"


def _decode_state(state: str) -> dict[str, Any]:
    try:
        encoded_payload, signature = state.split(".", 1)
    except ValueError as exc:
        raise BotOAuthError("Invalid Slack OAuth state") from exc
    expected = _sign(encoded_payload)
    if not hmac.compare_digest(expected, signature):
        raise BotOAuthError("Invalid Slack OAuth state")
    try:
        payload = json.loads(_b64url_decode(encoded_payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise BotOAuthError("Invalid Slack OAuth state") from exc
    if not isinstance(payload, dict):
        raise BotOAuthError("Invalid Slack OAuth state")
    exp = payload.get("exp")
    if not isinstance(exp, int) or datetime.now(tz=UTC).timestamp() >= exp:
        raise BotOAuthError("Slack OAuth state expired")
    return payload


def _sign(value: str) -> str:
    digest = hmac.new(
        settings.app_auth_secret.get_secret_value().encode(),
        value.encode(),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(digest)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64url_decode(raw: str) -> bytes:
    padded = raw + "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(padded.encode())


def _as_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise BotOAuthError("Slack OAuth token response is missing required metadata")
    return value.strip()
