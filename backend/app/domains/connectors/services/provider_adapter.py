"""Provider adapter interface and error taxonomy for the connector sync engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.workers.base_task import PermanentTaskError, TransientTaskError


class ConnectorAuthError(PermanentTaskError):
    """OAuth token invalid or revoked; connection must be re-authorized."""


class ConnectorPermissionError(PermanentTaskError):
    """Caller lacks permission to read a source or item."""


class ConnectorContentError(PermanentTaskError):
    """Item content is unreadable or unsupported; skip item but continue sync."""


class ConnectorRateLimitError(TransientTaskError):
    """Provider responded with 429; retry after the given delay."""

    def __init__(self, message: str, *, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds or 60


class ConnectorProviderUnavailableError(TransientTaskError):
    """Provider returned 5xx or timed out; retry with backoff."""


class ConnectorIngestionError(TransientTaskError):
    """Downstream ingestion step (e.g. embedding) failed transiently."""


class ConnectorAdapterNotFoundError(PermanentTaskError):
    """No sync adapter is registered for the requested provider key."""


@dataclass
class ItemPage:
    items: list[NormalizedExternalItem]
    next_cursor: dict | None = None
    has_more: bool = False


@dataclass
class DeltaItem:
    provider_item_id: str
    is_deleted: bool = False
    permission_revoked: bool = False
    item: NormalizedExternalItem | None = None


@dataclass
class DeltaPage:
    items: list[DeltaItem] = field(default_factory=list)
    next_cursor: dict | None = None
    has_more: bool = False


class ConnectorProviderAdapter(ABC):
    """Abstract base for provider-specific sync adapters.

    Each adapter is stateless; all I/O context (connection, decrypted credential,
    source config) is passed per-call so adapters can be reused across organizations.
    """

    @abstractmethod
    async def list_items(
        self,
        *,
        organization_id: str,
        connection_id: str,
        external_source_id: str | None,
        provider_source_id: str | None,
        decrypted_credential: dict,
        cursor: dict,
        page_size: int,
    ) -> ItemPage:
        """Full-sync page fetch.  Return all items visible to the credential."""

    @abstractmethod
    async def delta_sync(
        self,
        *,
        organization_id: str,
        connection_id: str,
        external_source_id: str | None,
        provider_source_id: str | None,
        decrypted_credential: dict,
        cursor: dict,
        page_size: int,
    ) -> DeltaPage:
        """Incremental-sync page fetch.  Return only items changed since cursor."""

    async def fetch_attachments(
        self,
        *,
        provider_item_id: str,
        decrypted_credential: dict,
    ) -> list[NormalizedExternalItem]:
        """Optional: return attachment items for the given parent item."""
        return []

    async def download_file_content(
        self,
        *,
        provider_item_id: str,
        mime_type: str | None,
        decrypted_credential: dict,
    ) -> tuple[bytes, str, str] | None:
        """Download raw file bytes for a file/attachment item.

        Returns (content_bytes, filename, resolved_mime_type) or None if the item
        is not downloadable (e.g. it is a folder, comment, or unsupported format).
        Implementations should map provider-native formats (e.g. Google Docs) to a
        supported MIME type (application/pdf or text/plain) before returning.
        """
        return None


class SyncAdapterRegistry:
    """Maps provider keys to their concrete ConnectorProviderAdapter implementations."""

    def __init__(self) -> None:
        self._adapters: dict[str, ConnectorProviderAdapter] = {}

    def register(self, provider_key: str, adapter: ConnectorProviderAdapter) -> None:
        self._adapters[provider_key.strip().lower()] = adapter

    def get(self, provider_key: str) -> ConnectorProviderAdapter | None:
        return self._adapters.get(provider_key.strip().lower())

    def require(self, provider_key: str) -> ConnectorProviderAdapter:
        adapter = self.get(provider_key)
        if adapter is None:
            raise ConnectorAdapterNotFoundError(
                f"No sync adapter registered for provider '{provider_key}'. "
                "Register an adapter with default_sync_adapter_registry.register()."
            )
        return adapter


default_sync_adapter_registry = SyncAdapterRegistry()
