from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ConnectorOAuthClientSettings, settings
from app.domains.admin.services.audit_service import AuditLogService, sanitize_metadata
from app.domains.connectors.audit import ConnectorAuditAction
from app.domains.connectors.repositories.connectors import ConnectorRepository
from app.domains.connectors.schemas.credentials import OAuthCredentialPayload, OAuthTokenResponse
from app.domains.connectors.services.connector_service import (
    ConnectorBoundaryError,
    ConnectorPlatformService,
)
from app.domains.connectors.services.credential_vault import (
    ConnectorCredentialError,
    ConnectorCredentialVault,
)
from app.domains.connectors.services.provider_registry import (
    ProviderRegistry,
    default_provider_registry,
)
from app.models.connector import ConnectorConnection, ConnectorProvider
from app.models.connector_credential import ConnectorCredential, ConnectorOAuthState
from app.models.enums import (
    ConnectorConnectionStatus,
    ConnectorCredentialStatus,
)

_ATLASSIAN_PROVIDER_KEYS: frozenset[str] = frozenset({"jira", "confluence"})


class OAuthLifecycleError(ValueError):
    """Base safe error for connector OAuth lifecycle failures."""


class OAuthStateValidationError(OAuthLifecycleError):
    """Raised when OAuth callback state is missing, expired, reused, or invalid."""


class OAuthRefreshError(OAuthLifecycleError):
    """Raised when OAuth refresh fails and the connector must stop syncing."""


class ConnectorSyncBlockedError(OAuthLifecycleError):
    """Raised when a disabled or revoked connection is requested for sync."""


class OAuthTokenClient(Protocol):
    async def exchange_code(
        self,
        *,
        provider_key: str,
        code: str,
        redirect_uri: str,
        scopes: list[str],
    ) -> OAuthTokenResponse: ...

    async def refresh(
        self,
        *,
        provider_key: str,
        refresh_token: str,
        scopes: list[str],
    ) -> OAuthTokenResponse: ...

    async def revoke(
        self,
        *,
        provider_key: str,
        token: str,
        token_type_hint: str,
    ) -> None: ...


@dataclass(frozen=True)
class OAuthConnectResult:
    state: str
    authorization_url: str
    expires_at: datetime
    scopes: list[str]


class ConnectorOAuthLifecycleService:
    def __init__(
        self,
        *,
        repository: ConnectorRepository | None = None,
        platform_service: ConnectorPlatformService | None = None,
        provider_registry: ProviderRegistry | None = None,
        vault: ConnectorCredentialVault | None = None,
        token_client: OAuthTokenClient | None = None,
        audit_service: AuditLogService | None = None,
        oauth_client_settings: list[ConnectorOAuthClientSettings] | None = None,
        state_ttl_seconds: int = 600,
        refresh_skew_seconds: int = 60,
    ) -> None:
        self.repository = repository or ConnectorRepository()
        self.provider_registry = provider_registry or default_provider_registry
        self.platform_service = platform_service or ConnectorPlatformService(
            repository=self.repository,
            provider_registry=self.provider_registry,
        )
        self.vault = vault or ConnectorCredentialVault(repository=self.repository)
        self.token_client = token_client
        self.audit_service = audit_service or AuditLogService()
        self.oauth_client_settings = (
            oauth_client_settings
            if oauth_client_settings is not None
            else list(settings.connector_oauth_clients)
        )
        self.state_ttl_seconds = state_ttl_seconds
        self.refresh_skew_seconds = refresh_skew_seconds

    async def begin_connect(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        provider_key: str,
        redirect_uri: str,
        user_id: UUID | None = None,
        requested_scopes: list[str] | None = None,
        collection_id: UUID | None = None,
        connection_id: UUID | None = None,
        display_name: str | None = None,
        external_account_id: str | None = None,
        client_id: str | None = None,
        config: dict | None = None,
        now: datetime | None = None,
    ) -> OAuthConnectResult:
        provider = self.provider_registry.require(provider_key)
        if provider.oauth is None:
            raise OAuthLifecycleError("connector provider does not support OAuth")
        scopes = self.provider_registry.validate_scopes(provider_key, requested_scopes)
        client_config = self._require_oauth_client(provider_key)
        effective_redirect_uri = (
            str(client_config.redirect_uri) if client_config.redirect_uri else redirect_uri
        )
        if collection_id is not None:
            await self.platform_service.require_collection(session, organization_id, collection_id)
        if connection_id is not None:
            await self.platform_service.require_connection(session, organization_id, connection_id)

        state = secrets.token_urlsafe(32)
        current_time = now or datetime.now(tz=UTC)
        expires_at = current_time + timedelta(seconds=self.state_ttl_seconds)
        await self.repository.create_oauth_state(
            session,
            organization_id=organization_id,
            provider_key=provider.key,
            state_hash=_hash_state(state),
            redirect_uri=effective_redirect_uri,
            requested_scopes=scopes,
            expires_at=expires_at,
            created_by_user_id=user_id,
            connection_id=connection_id,
            collection_id=collection_id,
            display_name=display_name,
            external_account_id=external_account_id,
            config={
                "client_id_set": bool(client_config.client_id),
                "redirect_uri": effective_redirect_uri,
                **(config or {}),
            },
        )
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.oauth_connect_started.value,
            resource_id=connection_id,
            metadata={
                "provider_key": provider.key,
                "scopes": scopes,
                "collection_id": str(collection_id) if collection_id else None,
                "display_name": display_name,
            },
        )
        return OAuthConnectResult(
            state=state,
            authorization_url=_authorization_url(
                authorization_endpoint=provider.oauth.authorization_endpoint,
                state=state,
                redirect_uri=effective_redirect_uri,
                scopes=scopes,
                client_id=client_config.client_id,
                additional_params=provider.oauth.additional_authorization_params,
            ),
            expires_at=expires_at,
            scopes=scopes,
        )

    async def complete_callback(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        state: str,
        code: str | None = None,
        error: str | None = None,
        user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> ConnectorConnection:
        current_time = now or datetime.now(tz=UTC)
        oauth_state = await self._require_valid_state(
            session,
            organization_id=organization_id,
            state=state,
            now=current_time,
        )
        return await self._complete_callback_for_state(
            session,
            oauth_state=oauth_state,
            organization_id=organization_id,
            state=state,
            code=code,
            error=error,
            user_id=user_id,
            now=current_time,
        )

    async def complete_callback_public(
        self,
        session: AsyncSession,
        *,
        state: str,
        code: str | None = None,
        error: str | None = None,
        now: datetime | None = None,
    ) -> ConnectorConnection:
        current_time = now or datetime.now(tz=UTC)
        oauth_state = await self._require_valid_state_by_hash(
            session,
            state=state,
            now=current_time,
        )
        return await self._complete_callback_for_state(
            session,
            oauth_state=oauth_state,
            organization_id=oauth_state.organization_id,
            state=state,
            code=code,
            error=error,
            user_id=oauth_state.created_by_user_id,
            now=current_time,
        )

    async def get_valid_oauth_payload(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        now: datetime | None = None,
    ) -> OAuthCredentialPayload:
        current_time = now or datetime.now(tz=UTC)
        connection = await self.platform_service.require_connection(
            session, organization_id, connection_id
        )
        if connection.status != ConnectorConnectionStatus.active.value:
            raise ConnectorSyncBlockedError("connector connection is not active")

        credential, payload = await self.vault.load_current(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        if not isinstance(payload, OAuthCredentialPayload):
            raise ConnectorCredentialError("connector credential is not OAuth")
        if _is_expired(
            credential.expires_at or payload.expires_at, current_time, self.refresh_skew_seconds
        ):
            return await self.refresh_oauth_credential(
                session,
                organization_id=organization_id,
                connection_id=connection_id,
                now=current_time,
            )

        await self.vault.mark_used(session, credential=credential, used_at=current_time)
        return payload

    async def refresh_oauth_credential(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        now: datetime | None = None,
    ) -> OAuthCredentialPayload:
        current_time = now or datetime.now(tz=UTC)
        if self.token_client is None:
            raise OAuthRefreshError("OAuth token client is not configured")
        connection = await self.platform_service.require_connection(
            session, organization_id, connection_id
        )
        credential, payload = await self.vault.load_current(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        if not isinstance(payload, OAuthCredentialPayload) or payload.refresh_token is None:
            await self._mark_refresh_failed(
                session,
                connection=connection,
                credential=credential,
                reason="missing_refresh_token",
            )
            raise OAuthRefreshError("connector credential cannot be refreshed")

        try:
            token_response = await self.token_client.refresh(
                provider_key=await self._provider_key(session, connection),
                refresh_token=payload.refresh_token,
                scopes=list(credential.scopes_json or payload.scopes),
            )
        except Exception as exc:
            await self._mark_refresh_failed(
                session,
                connection=connection,
                credential=credential,
                reason=exc.__class__.__name__,
            )
            await self._audit(
                session,
                organization_id=organization_id,
                user_id=None,
                action="connector.oauth.refresh_failed",
                resource_id=connection.id,
                metadata={
                    "provider_key": await self._provider_key(session, connection),
                    "reason": exc.__class__.__name__,
                },
            )
            raise OAuthRefreshError("connector credential refresh failed") from exc

        provider_key = await self._provider_key(session, connection)
        scopes = self.provider_registry.validate_scopes(
            provider_key,
            token_response.resolved_scopes(list(credential.scopes_json or payload.scopes)),
        )
        refreshed_payload = OAuthCredentialPayload(
            access_token=token_response.access_token,
            refresh_token=token_response.refresh_token or payload.refresh_token,
            token_type=token_response.token_type,
            expires_at=_resolve_expires_at(token_response, current_time),
            scopes=scopes,
            provider_account_id=token_response.provider_account_id or payload.provider_account_id,
        )
        await self.vault.store(
            session,
            connection=connection,
            payload=refreshed_payload,
            scopes=scopes,
            metadata={
                "provider_key": provider_key,
                "oauth_flow": "refresh",
                "has_refresh_token": refreshed_payload.refresh_token is not None,
            },
            issued_at=current_time,
            expires_at=refreshed_payload.expires_at,
            refreshed=True,
        )
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=None,
            action="connector.oauth.token_refreshed",
            resource_id=connection.id,
            metadata={
                "provider_key": provider_key,
                "scopes": scopes,
                "expires_at": refreshed_payload.expires_at.isoformat()
                if refreshed_payload.expires_at
                else None,
            },
        )
        return refreshed_payload

    async def disconnect(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> dict:
        current_time = now or datetime.now(tz=UTC)
        connection = await self.platform_service.require_connection(
            session, organization_id, connection_id
        )
        revoked_tokens = 0
        credential: ConnectorCredential | None = await self.repository.get_current_credential(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        if credential is not None:
            try:
                _, payload = await self.vault.load_current(
                    session,
                    organization_id=organization_id,
                    connection_id=connection_id,
                )
            except ConnectorCredentialError:
                payload = None
            if (
                self.token_client is not None
                and isinstance(payload, OAuthCredentialPayload)
                and payload.access_token
            ):
                revoked_tokens += await self._revoke_remote_tokens(
                    provider_key=await self._provider_key(session, connection),
                    payload=payload,
                )
            await self.repository.mark_credential_status(
                session,
                credential=credential,
                status=ConnectorCredentialStatus.revoked.value,
                revoked_at=current_time,
            )
            credential.status = ConnectorCredentialStatus.revoked.value
            credential.revoked_at = current_time
            await self.repository.update_connection_auth_metadata(
                session,
                connection=connection,
                auth_config=self.vault.safe_connection_auth_config(connection, credential),
                status=ConnectorConnectionStatus.revoked,
                error_message=None,
            )
        else:
            await self.repository.update_connection_auth_metadata(
                session,
                connection=connection,
                auth_config=sanitize_metadata(connection.auth_config_json),
                status=ConnectorConnectionStatus.revoked,
                error_message=None,
            )

        disabled_jobs = await self.repository.disable_sync_jobs_for_connection(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action="connector.connection.revoked",
            resource_id=connection.id,
            metadata={
                "provider_key": await self._provider_key(session, connection),
                "disabled_sync_jobs": disabled_jobs,
                "remote_revoked_token_count": revoked_tokens,
            },
        )
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.connection_disconnected.value,
            resource_id=connection.id,
            metadata={
                "provider_key": await self._provider_key(session, connection),
                "status": ConnectorConnectionStatus.revoked.value,
            },
        )
        return {
            "connection_id": str(connection.id),
            "status": ConnectorConnectionStatus.revoked.value,
            "disabled_sync_jobs": disabled_jobs,
            "remote_revoked_token_count": revoked_tokens,
        }

    async def delete_connection(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
        user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        """Disconnect (revoke tokens) then hard-delete the connection record."""
        await self.disconnect(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
            user_id=user_id,
            now=now,
        )
        connection = await self.platform_service.require_connection(
            session, organization_id, connection_id
        )
        await self.repository.delete_connection(session, connection_id=connection_id)
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=ConnectorAuditAction.connection_deleted.value,
            resource_id=connection_id,
            metadata={
                "provider_key": await self._provider_key(session, connection),
                "status": ConnectorConnectionStatus.revoked.value,
            },
        )

    async def diagnostics(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        connection_id: UUID,
    ) -> dict:
        connection = await self.platform_service.require_connection(
            session, organization_id, connection_id
        )
        credential = await self.repository.get_current_credential(
            session,
            organization_id=organization_id,
            connection_id=connection_id,
        )
        auth_config = sanitize_metadata(connection.auth_config_json)
        return {
            "connection_id": str(connection.id),
            "provider_key": await self._provider_key(session, connection),
            "status": connection.status,
            "error_message": connection.error_message,
            "auth_type": credential.auth_type if credential is not None else None,
            "credential_status": credential.status if credential is not None else None,
            "credential_version": credential.version if credential is not None else None,
            "credential_fingerprint": credential.secret_fingerprint
            if credential is not None
            else None,
            "scopes": list(credential.scopes_json or []) if credential is not None else [],
            "expires_at": credential.expires_at.isoformat()
            if credential is not None and credential.expires_at is not None
            else None,
            "metadata": auth_config,
        }

    async def _require_valid_state(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        state: str,
        now: datetime,
    ) -> ConnectorOAuthState:
        state_hash = _hash_state(state)
        oauth_state = await self.repository.get_oauth_state_by_hash(
            session,
            organization_id=organization_id,
            state_hash=state_hash,
        )
        if oauth_state is None:
            raise OAuthStateValidationError("OAuth state is invalid")
        if oauth_state.consumed_at is not None:
            raise OAuthStateValidationError("OAuth state has already been used")
        if _as_aware(oauth_state.expires_at) <= now:
            await self.repository.consume_oauth_state(
                session,
                state=oauth_state,
                consumed_at=now,
                failure_reason="expired",
            )
            raise OAuthStateValidationError("OAuth state has expired")
        return oauth_state

    async def _require_valid_state_by_hash(
        self,
        session: AsyncSession,
        *,
        state: str,
        now: datetime,
    ) -> ConnectorOAuthState:
        state_hash = _hash_state(state)
        oauth_state = await self.repository.get_oauth_state_by_hash_any(
            session,
            state_hash=state_hash,
        )
        if oauth_state is None:
            raise OAuthStateValidationError("OAuth state is invalid")
        if oauth_state.consumed_at is not None:
            raise OAuthStateValidationError("OAuth state has already been used")
        if _as_aware(oauth_state.expires_at) <= now:
            await self.repository.consume_oauth_state(
                session,
                state=oauth_state,
                consumed_at=now,
                failure_reason="expired",
            )
            raise OAuthStateValidationError("OAuth state has expired")
        return oauth_state

    async def _complete_callback_for_state(
        self,
        session: AsyncSession,
        *,
        oauth_state: ConnectorOAuthState,
        organization_id: UUID,
        state: str,
        code: str | None,
        error: str | None,
        user_id: UUID | None,
        now: datetime,
    ) -> ConnectorConnection:
        del state
        if error is not None:
            await self.repository.consume_oauth_state(
                session,
                state=oauth_state,
                consumed_at=now,
                failure_reason="provider_error",
            )
            await self._audit(
                session,
                organization_id=organization_id,
                user_id=user_id,
                action="connector.oauth.callback_failed",
                resource_id=oauth_state.connection_id,
                metadata={
                    "provider_key": oauth_state.provider_key,
                    "reason": "provider_error",
                    "error": error,
                },
            )
            raise OAuthStateValidationError("OAuth provider returned an error")

        if code is None or not code.strip():
            raise OAuthStateValidationError("OAuth callback code is required")
        if self.token_client is None:
            raise OAuthLifecycleError("OAuth token client is not configured")

        token_response = await self.token_client.exchange_code(
            provider_key=oauth_state.provider_key,
            code=code.strip(),
            redirect_uri=oauth_state.redirect_uri,
            scopes=list(oauth_state.requested_scopes_json or []),
        )
        scopes = self.provider_registry.validate_scopes(
            oauth_state.provider_key,
            token_response.resolved_scopes(list(oauth_state.requested_scopes_json or [])),
        )
        expires_at = _resolve_expires_at(token_response, now)
        payload = OAuthCredentialPayload(
            access_token=token_response.access_token,
            refresh_token=token_response.refresh_token,
            token_type=token_response.token_type,
            expires_at=expires_at,
            scopes=scopes,
            provider_account_id=token_response.provider_account_id,
        )
        connection = await self._connection_for_state(
            session,
            organization_id=organization_id,
            oauth_state=oauth_state,
            external_account_id=token_response.provider_account_id,
        )
        await self.vault.store(
            session,
            connection=connection,
            payload=payload,
            scopes=scopes,
            metadata={
                "provider_key": oauth_state.provider_key,
                "oauth_flow": "callback",
                "has_refresh_token": token_response.refresh_token is not None,
                **(oauth_state.config_json or {}),
            },
            issued_at=now,
            expires_at=expires_at,
        )
        await self.repository.consume_oauth_state(
            session,
            state=oauth_state,
            consumed_at=now,
        )
        await self._audit(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action="connector.oauth.connected"
            if oauth_state.connection_id is None
            else "connector.oauth.reconnected",
            resource_id=connection.id,
            metadata={
                "provider_key": oauth_state.provider_key,
                "scopes": scopes,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
        return connection

    async def _connection_for_state(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        oauth_state: ConnectorOAuthState,
        external_account_id: str | None,
    ) -> ConnectorConnection:
        if oauth_state.connection_id is not None:
            return await self.platform_service.require_connection(
                session, organization_id, oauth_state.connection_id
            )
        try:
            return await self.platform_service.create_connection(
                session,
                organization_id=organization_id,
                provider_key=oauth_state.provider_key,
                display_name=oauth_state.display_name or oauth_state.provider_key,
                collection_id=oauth_state.collection_id,
                created_by_user_id=oauth_state.created_by_user_id,
                external_account_id=external_account_id or oauth_state.external_account_id,
                auth_config={
                    "provider_key": oauth_state.provider_key,
                    **(oauth_state.config_json or {}),
                },
            )
        except ConnectorBoundaryError:
            raise

    async def _mark_refresh_failed(
        self,
        session: AsyncSession,
        *,
        connection: ConnectorConnection,
        credential: ConnectorCredential,
        reason: str,
    ) -> None:
        await self.repository.mark_credential_status(
            session,
            credential=credential,
            status=ConnectorCredentialStatus.error.value,
            error_message="refresh_failed",
        )
        await self.repository.update_connection_auth_metadata(
            session,
            connection=connection,
            auth_config=sanitize_metadata(
                {
                    **(connection.auth_config_json or {}),
                    "credential_status": ConnectorCredentialStatus.error.value,
                    "refresh_error": reason,
                }
            ),
            status=ConnectorConnectionStatus.error,
            error_message="Connector credential refresh failed",
        )

    async def _revoke_remote_tokens(
        self,
        *,
        provider_key: str,
        payload: OAuthCredentialPayload,
    ) -> int:
        if self.token_client is None:
            return 0
        revoked_tokens = 0
        if payload.refresh_token:
            await self.token_client.revoke(
                provider_key=provider_key,
                token=payload.refresh_token,
                token_type_hint="refresh_token",
            )
            revoked_tokens += 1
        await self.token_client.revoke(
            provider_key=provider_key,
            token=payload.access_token,
            token_type_hint="access_token",
        )
        revoked_tokens += 1
        return revoked_tokens

    async def _provider_key(
        self,
        session: AsyncSession,
        connection: ConnectorConnection,
    ) -> str:
        auth_config_provider_key = (connection.auth_config_json or {}).get("provider_key")
        if isinstance(auth_config_provider_key, str) and auth_config_provider_key.strip():
            return auth_config_provider_key.strip().lower()
        result = await session.execute(
            select(ConnectorProvider.key).where(ConnectorProvider.id == connection.provider_id)
        )
        provider_key = result.scalar_one()
        return provider_key.strip().lower()

    async def _audit(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        action: str,
        resource_id: UUID | None,
        metadata: dict,
    ) -> None:
        await self.audit_service.record(
            session,
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type="connector_connection",
            resource_id=resource_id,
            metadata=metadata,
        )

    def _require_oauth_client(self, provider_key: str) -> ConnectorOAuthClientSettings:
        normalized_provider_key = provider_key.strip().lower()
        for client_config in self.oauth_client_settings:
            if client_config.provider_key == normalized_provider_key:
                return client_config
        # Atlassian providers (jira, confluence) can share a single "atlassian" credential entry.
        if normalized_provider_key in _ATLASSIAN_PROVIDER_KEYS:
            for client_config in self.oauth_client_settings:
                if client_config.provider_key == "atlassian":
                    return client_config
        raise OAuthLifecycleError(
            f"connector OAuth client is not configured for provider {normalized_provider_key!r}. "
            f"Add an entry with provider_key={normalized_provider_key!r} "
            f"(or 'atlassian' to cover all Atlassian products) to CONNECTOR_OAUTH_CLIENTS."
        )


def _hash_state(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _authorization_url(
    *,
    authorization_endpoint: str,
    state: str,
    redirect_uri: str,
    scopes: list[str],
    client_id: str | None,
    additional_params: dict[str, str],
) -> str:
    query = {
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        **additional_params,
    }
    if client_id is not None:
        query["client_id"] = client_id
    return f"{authorization_endpoint}?{urlencode(query)}"


def _resolve_expires_at(response: OAuthTokenResponse, now: datetime) -> datetime | None:
    if response.expires_at is not None:
        return _as_aware(response.expires_at)
    if response.expires_in is None:
        return None
    return now + timedelta(seconds=response.expires_in)


def _is_expired(
    expires_at: datetime | None,
    now: datetime,
    refresh_skew_seconds: int,
) -> bool:
    if expires_at is None:
        return False
    return _as_aware(expires_at) <= now + timedelta(seconds=refresh_skew_seconds)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
