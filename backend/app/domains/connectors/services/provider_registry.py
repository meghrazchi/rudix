from __future__ import annotations

from app.domains.connectors.schemas.connectors import (
    ProviderCapabilities,
    ProviderExportFormat,
    ProviderOAuthConfig,
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

    def validate_scopes(
        self,
        provider_key: str,
        requested_scopes: list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        provider = self.require(provider_key)
        if provider.oauth is None:
            if requested_scopes:
                raise ProviderRegistryError(
                    f"connector provider does not accept OAuth scopes: {provider.key}"
                )
            return []

        scopes = _dedupe_scopes(requested_scopes or provider.oauth.default_scopes)
        missing_required = set(provider.oauth.required_scopes).difference(scopes)
        if missing_required:
            missing_text = ", ".join(sorted(missing_required))
            raise ProviderRegistryError(
                f"requested OAuth scopes are missing required scopes: {missing_text}"
            )

        unsupported = set(scopes).difference(provider.oauth.allowed_scopes)
        if unsupported:
            unsupported_text = ", ".join(sorted(unsupported))
            raise ProviderRegistryError(
                f"requested OAuth scopes are not allowed for {provider.key}: {unsupported_text}"
            )
        return scopes

    def list(self) -> list[ProviderRegistration]:
        return [self._providers[key] for key in sorted(self._providers)]


def build_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    for provider in (
        _confluence_provider(),
        _google_drive_provider(),
        _microsoft_sharepoint_onedrive_provider(),
    ):
        registry.register(provider)
    return registry


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
                "site_url": {
                    "type": "string",
                    "format": "uri",
                    "title": "Confluence site URL",
                    "description": "Your Atlassian site, for example https://myteam.atlassian.net.",
                },
                "space_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Space keys",
                    "description": "Comma-separated Confluence space keys to sync. Leave blank to sync all accessible spaces.",
                },
                "cql_filter": {
                    "type": "string",
                    "title": "CQL filter",
                    "description": "Additional Confluence query predicate applied to every sync.",
                },
                "include_comments": {
                    "type": "boolean",
                    "title": "Include page comments",
                    "description": "Import page comments as searchable items.",
                },
            },
            "required": ["site_url"],
            "additionalProperties": False,
        },
        oauth=ProviderOAuthConfig(
            authorization_endpoint="https://auth.atlassian.com/authorize",
            token_endpoint="https://auth.atlassian.com/oauth/token",
            revoke_endpoint="https://auth.atlassian.com/oauth/token/revoke",
            default_scopes=(
                "read:confluence-content.all",
                "read:confluence-space.summary",
                "offline_access",
            ),
            required_scopes=("read:confluence-content.all",),
            optional_scopes=("read:confluence-space.summary", "offline_access"),
            additional_authorization_params={"audience": "api.atlassian.com"},
        ),
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
                "folder_ids": {"type": "array", "items": {"type": "string"}},
                "drive_ids": {"type": "array", "items": {"type": "string"}},
                "include_shared_drives": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        oauth=ProviderOAuthConfig(
            authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
            token_endpoint="https://oauth2.googleapis.com/token",
            revoke_endpoint="https://oauth2.googleapis.com/revoke",
            default_scopes=("https://www.googleapis.com/auth/drive.readonly",),
            required_scopes=("https://www.googleapis.com/auth/drive.readonly",),
            optional_scopes=("https://www.googleapis.com/auth/drive.metadata.readonly",),
            additional_authorization_params={
                "access_type": "offline",
                "prompt": "consent",
            },
        ),
    )


def _microsoft_sharepoint_onedrive_provider() -> ProviderRegistration:
    return ProviderRegistration(
        key="microsoft-sharepoint-onedrive",
        display_name="Microsoft SharePoint / OneDrive",
        capabilities=ProviderCapabilities(
            auth_type=ConnectorAuthType.oauth2,
            capabilities=frozenset(
                {
                    ConnectorCapability.acls,
                    ConnectorCapability.delta_sync,
                    ConnectorCapability.deletions,
                    ConnectorCapability.deep_links,
                    ConnectorCapability.files,
                    ConnectorCapability.folders,
                    ConnectorCapability.rate_limits,
                }
            ),
            rate_limits=(
                ProviderRateLimit(name="graph_api", max_requests=10_000, window_seconds=60),
            ),
            export_formats=(
                ProviderExportFormat(format="pdf", mime_type="application/pdf"),
                ProviderExportFormat(format="text", mime_type="text/plain"),
            ),
            max_page_size=200,
            notes=(
                "Connect a Microsoft 365 tenant, choose SharePoint sites, document libraries, "
                "folders, or OneDrive drives, and keep provenance and ACL metadata attached to "
                "every synced file."
            ),
        ),
        config_schema={
            "type": "object",
            "properties": {
                "site_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "SharePoint site IDs",
                    "description": "Composite IDs in the form site:<site-id>. Leave blank to discover sources first.",
                },
                "drive_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Drive IDs",
                    "description": "Composite IDs in the form drive:<drive-id> for SharePoint libraries or OneDrive drives.",
                },
                "folder_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Folder IDs",
                    "description": "Composite IDs in the form folder:<drive-id>:<folder-id> to scope sync to subfolders.",
                },
                "allowed_file_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Allowed file types",
                    "description": "Allowed MIME types or exports such as application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, text/plain, or text/markdown.",
                },
                "max_file_size_mb": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10_240,
                    "title": "Max file size (MB)",
                    "description": "Skip downloaded files larger than this limit before ingestion.",
                },
                "include_folder_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Include folder paths",
                    "description": "Only sync items whose relative folder path matches one of these prefixes.",
                },
                "exclude_folder_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "title": "Exclude folder paths",
                    "description": "Skip items under matching folder path prefixes.",
                },
                "sync_frequency_minutes": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 10_080,
                    "title": "Sync frequency (minutes)",
                    "description": "Suggested sync cadence for this source set.",
                },
                "max_downloads_per_sync": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100_000,
                    "title": "Max downloads per sync",
                    "description": "Safety cap for downloaded files during a single sync run.",
                },
                "permission_import_behavior": {
                    "type": "string",
                    "enum": ["none", "direct"],
                    "title": "Permission import behavior",
                    "description": "Choose whether to import direct SharePoint/OneDrive permissions for ACL-aware citations.",
                },
            },
            "additionalProperties": False,
        },
        oauth=ProviderOAuthConfig(
            authorization_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            token_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            revoke_endpoint=None,
            default_scopes=(
                "offline_access",
                "Files.Read.All",
                "Sites.Read.All",
            ),
            required_scopes=(
                "Files.Read.All",
                "Sites.Read.All",
            ),
            optional_scopes=("offline_access",),
            additional_authorization_params={
                "prompt": "select_account",
            },
        ),
    )


def _dedupe_scopes(scopes: list[str] | tuple[str, ...]) -> list[str]:
    normalized_scopes: list[str] = []
    for raw_scope in scopes:
        scope = raw_scope.strip()
        if scope and scope not in normalized_scopes:
            normalized_scopes.append(scope)
    return normalized_scopes


default_provider_registry = build_default_provider_registry()
