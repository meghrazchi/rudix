"""Provider paging (list_items / delta_sync) and OAuth credential refresh (R06-11 split)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domains.connectors.services.provider_adapter import DeltaPage, ItemPage
from app.domains.connectors.services.sync.common import DEFAULT_PAGE_SIZE, source_id_str
from app.models.connector import ConnectorConnection
from app.models.connector_credential import ConnectorCredential
from app.models.connector_sync import ConnectorSyncJob, ConnectorSyncRun
from app.models.enums import ConnectorAuthType

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine

_logger = get_logger("connectors.sync_engine")
_PROACTIVE_REFRESH_SECONDS = 60


def provider_source_id(job: ConnectorSyncJob) -> str | None:
    if job.external_source_id and hasattr(job, "external_source") and job.external_source:
        source_id: str | None = job.external_source.provider_source_id
        return source_id
    return None


class SyncFetcher:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    async def fetch_page(
        self,
        *,
        adapter: Any,
        run: ConnectorSyncRun,
        job: ConnectorSyncJob,
        decrypted_credential: dict,
        cursor: dict,
        incremental: bool,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Any:
        """One provider call (an ``ItemPage`` or ``DeltaPage``); uses no database session."""
        call = adapter.delta_sync if incremental else adapter.list_items
        page: ItemPage | DeltaPage = await call(
            organization_id=str(run.organization_id),
            connection_id=str(run.connection_id),
            external_source_id=source_id_str(run),
            provider_source_id=provider_source_id(job),
            decrypted_credential=decrypted_credential,
            cursor=cursor,
            page_size=page_size,
        )
        return page

    async def refresh_oauth_if_needed(
        self,
        session: AsyncSession,
        *,
        connection: ConnectorConnection,
        credential: ConnectorCredential,
        organization_id: UUID,
    ) -> ConnectorCredential:
        """Proactively refresh an OAuth credential that is expired or near expiry.

        Returns the refreshed credential if refresh succeeded, otherwise the original.
        No-ops when oauth_lifecycle is not configured or credential is not OAuth.
        """
        lifecycle = self.engine._oauth_lifecycle
        if lifecycle is None or credential.auth_type != ConnectorAuthType.oauth2.value:
            return credential
        expires_at = credential.expires_at
        if expires_at is None:
            return credential
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at > datetime.now(UTC) + timedelta(seconds=_PROACTIVE_REFRESH_SECONDS):
            return credential

        _logger.info(
            "connector.sync.proactive_token_refresh",
            connection_id=str(connection.id),
            provider_key=getattr(getattr(connection, "provider", None), "key", None),
            expires_at=expires_at.isoformat(),
        )
        try:
            await lifecycle.refresh_oauth_credential(
                session, organization_id=organization_id, connection_id=connection.id
            )
            refreshed = await self.engine.repository.get_current_credential(
                session, organization_id=organization_id, connection_id=connection.id
            )
            if refreshed is not None:
                return refreshed
        except Exception as exc:
            _logger.warning(
                "connector.sync.proactive_token_refresh_failed",
                connection_id=str(connection.id),
                error=str(exc)[:200],
            )
        return credential

    async def refreshed_credential(
        self,
        session: AsyncSession,
        *,
        connection: ConnectorConnection,
        credential: ConnectorCredential,
        organization_id: UUID,
    ) -> dict | None:
        """After an auth error: refresh the OAuth token and return the new decrypted secret.

        None when the connection is not OAuth, no lifecycle service is configured, or the
        refresh fails.
        """
        lifecycle = self.engine._oauth_lifecycle
        if lifecycle is None or credential.auth_type != ConnectorAuthType.oauth2.value:
            return None
        _logger.info(
            "connector.sync.auth_error_refresh_attempt",
            connection_id=str(connection.id),
            provider_key=getattr(getattr(connection, "provider", None), "key", None),
        )
        try:
            await lifecycle.refresh_oauth_credential(
                session, organization_id=organization_id, connection_id=connection.id
            )
            new_credential = await self.engine.repository.get_current_credential(
                session, organization_id=organization_id, connection_id=connection.id
            )
            if new_credential is None:
                return None
            decrypted: dict = self.engine.credential_vault.decrypt(new_credential)
        except Exception as exc:
            _logger.warning(
                "connector.sync.auth_error_refresh_failed",
                connection_id=str(connection.id),
                error=str(exc)[:200],
            )
            return None
        _logger.info("connector.sync.auth_error_retry", connection_id=str(connection.id))
        return decrypted
