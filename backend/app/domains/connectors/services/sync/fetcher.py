"""Provider paging (list_items / delta_sync) and OAuth credential refresh (R06-11 split)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_connector_sync_rate_limited
from app.domains.connectors.services.provider_adapter import ConnectorRateLimitError
from app.domains.connectors.services.sync.context import RunContext
from app.models.connector import ConnectorConnection
from app.models.connector_credential import ConnectorCredential
from app.models.connector_sync import ConnectorSyncJob
from app.models.enums import ConnectorAuthType

if TYPE_CHECKING:
    from app.domains.connectors.services.sync_engine import ConnectorSyncEngine

_logger = get_logger("connectors.sync_engine")
_PROACTIVE_REFRESH_SECONDS = 60
_HEARTBEAT_EVERY_SECONDS = 15.0


class RateLimitDeferred(Exception):
    """The provider asked to wait longer than the inline backoff allows."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


def provider_source_id(job: ConnectorSyncJob) -> str | None:
    if job.external_source_id and hasattr(job, "external_source") and job.external_source:
        source_id: str | None = job.external_source.provider_source_id
        return source_id
    return None


class SyncFetcher:
    def __init__(self, engine: ConnectorSyncEngine) -> None:
        self.engine = engine

    async def fetch_page(self, ctx: RunContext, cursor: dict) -> Any:
        """One provider call (an ``ItemPage`` or ``DeltaPage``); uses no database session."""
        call = ctx.adapter.delta_sync if ctx.incremental else ctx.adapter.list_items
        return await call(
            organization_id=str(ctx.organization_id),
            connection_id=str(ctx.connection_id),
            external_source_id=str(ctx.external_source_id) if ctx.external_source_id else None,
            provider_source_id=ctx.provider_source_id,
            decrypted_credential=ctx.decrypted,
            cursor=cursor,
            page_size=settings.connector_sync_page_size,
        )

    async def fetch_with_backoff(
        self, ctx: RunContext, cursor: dict, heartbeat: Callable[[], Awaitable[None]]
    ) -> Any:
        """Fetch a page, honouring ``Retry-After`` inside the run.

        A rate limit of at most ``CONNECTOR_SYNC_MAX_INLINE_BACKOFF_SECONDS`` is slept (with
        heartbeats) and the same page retried, up to ``CONNECTOR_SYNC_MAX_INLINE_RETRIES``
        times; anything longer raises ``RateLimitDeferred`` so the run checkpoints and is
        re-enqueued with the provider's countdown instead of failing.
        """
        attempts = 0
        while True:
            try:
                return await self.fetch_page(ctx, cursor)
            except ConnectorRateLimitError as exc:
                retry_after = max(int(exc.retry_after_seconds), 0)
                inline = (
                    retry_after <= settings.connector_sync_max_inline_backoff_seconds
                    and attempts < settings.connector_sync_max_inline_retries
                )
                record_connector_sync_rate_limited(
                    ctx.provider_key, "inline" if inline else "requeued"
                )
                _logger.info(
                    "connector.sync.rate_limited",
                    sync_run_id=str(ctx.run_id),
                    organization_id=str(ctx.organization_id),
                    provider_key=ctx.provider_key,
                    retry_after_seconds=retry_after,
                    attempt=attempts + 1,
                    inline=inline,
                )
                if not inline:
                    raise RateLimitDeferred(max(retry_after, 1)) from exc
                attempts += 1
                await self._sleep_with_heartbeat(retry_after, heartbeat)

    async def _sleep_with_heartbeat(
        self, seconds: int, heartbeat: Callable[[], Awaitable[None]]
    ) -> None:
        remaining = float(seconds)
        while remaining > 0:
            step = min(remaining, _HEARTBEAT_EVERY_SECONDS)
            await self.engine.sleep(step)
            remaining -= step
            await heartbeat()

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
