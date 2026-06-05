from __future__ import annotations

from app.domains.connectors.schemas.connectors import (
    ProviderCapabilities,
    ProviderExportFormat,
    ProviderRateLimit,
    ProviderRegistration,
)
from app.models.enums import ConnectorAuthType, ConnectorCapability


class ProviderRegistryError(ValueError):
    """Raised when provider registration metadata is invalid."""


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderRegistration] = {}

    def register(self, provider: ProviderRegistration) -> None:
        if provider.key in self._providers:
            raise ProviderRegistryError(f"connector provider already registered: {provider.key}")
        self._providers[provider.key] = provider

    def get(self, provider_key: str) -> ProviderRegistration | None:
        return self._providers.get(provider_key.strip().lower())

    def require(self, provider_key: str) -> ProviderRegistration:
        provider = self.get(provider_key)
        if provider is None:
            raise ProviderRegistryError(f"connector provider is not registered: {provider_key}")
        return provider

    def list(self) -> list[ProviderRegistration]:
        return [self._providers[key] for key in sorted(self._providers)]


def build_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    for provider in (
        _jira_provider(),
        _confluence_provider(),
        _google_drive_provider(),
    ):
        registry.register(provider)
    return registry


def _jira_provider() -> ProviderRegistration:
    return ProviderRegistration(
        key="jira",
        display_name="Jira",
        capabilities=ProviderCapabilities(
            auth_type=ConnectorAuthType.oauth2,
            capabilities=frozenset(
                {
                    ConnectorCapability.attachments,
                    ConnectorCapability.comments,
                    ConnectorCapability.acls,
                    ConnectorCapability.delta_sync,
                    ConnectorCapability.rate_limits,
                    ConnectorCapability.webhooks,
                }
            ),
            rate_limits=(ProviderRateLimit(name="rest_api", max_requests=500, window_seconds=60),),
            export_formats=(
                ProviderExportFormat(format="issue_json", mime_type="application/json"),
            ),
            max_page_size=100,
        ),
        config_schema={
            "type": "object",
            "properties": {
                "site_url": {"type": "string", "format": "uri"},
                "project_keys": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["site_url"],
            "additionalProperties": False,
        },
    )


def _confluence_provider() -> ProviderRegistration:
    return ProviderRegistration(
        key="confluence",
        display_name="Confluence",
        capabilities=ProviderCapabilities(
            auth_type=ConnectorAuthType.oauth2,
            capabilities=frozenset(
                {
                    ConnectorCapability.attachments,
                    ConnectorCapability.comments,
                    ConnectorCapability.acls,
                    ConnectorCapability.delta_sync,
                    ConnectorCapability.export_formats,
                    ConnectorCapability.folders,
                    ConnectorCapability.rate_limits,
                    ConnectorCapability.webhooks,
                }
            ),
            rate_limits=(ProviderRateLimit(name="rest_api", max_requests=500, window_seconds=60),),
            export_formats=(
                ProviderExportFormat(format="storage", mime_type="text/html"),
                ProviderExportFormat(format="atlas_doc", mime_type="application/json"),
            ),
            max_page_size=100,
        ),
        config_schema={
            "type": "object",
            "properties": {
                "site_url": {"type": "string", "format": "uri"},
                "space_keys": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["site_url"],
            "additionalProperties": False,
        },
    )


def _google_drive_provider() -> ProviderRegistration:
    return ProviderRegistration(
        key="google_drive",
        display_name="Google Drive",
        capabilities=ProviderCapabilities(
            auth_type=ConnectorAuthType.oauth2,
            capabilities=frozenset(
                {
                    ConnectorCapability.attachments,
                    ConnectorCapability.acls,
                    ConnectorCapability.delta_sync,
                    ConnectorCapability.export_formats,
                    ConnectorCapability.folders,
                    ConnectorCapability.rate_limits,
                    ConnectorCapability.webhooks,
                }
            ),
            rate_limits=(
                ProviderRateLimit(name="drive_api", max_requests=12_000, window_seconds=60),
            ),
            export_formats=(
                ProviderExportFormat(format="text", mime_type="text/plain"),
                ProviderExportFormat(format="pdf", mime_type="application/pdf"),
            ),
            max_page_size=1000,
        ),
        config_schema={
            "type": "object",
            "properties": {
                "drive_ids": {"type": "array", "items": {"type": "string"}},
                "include_shared_drives": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    )


default_provider_registry = build_default_provider_registry()
