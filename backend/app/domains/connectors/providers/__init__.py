"""Connector provider adapters.

Importing this package registers all built-in provider adapters with
default_sync_adapter_registry so the sync engine can dispatch to them.
"""

from app.domains.connectors.providers.confluence.adapter import ConfluenceConnectorAdapter
from app.domains.connectors.providers.google_drive.adapter import GoogleDriveConnectorAdapter
from app.domains.connectors.providers.microsoft_sharepoint_onedrive.adapter import (
    MicrosoftSharePointOneDriveConnectorAdapter,
)
from app.domains.connectors.providers.notion.adapter import NotionConnectorAdapter
from app.domains.connectors.services.provider_adapter import default_sync_adapter_registry

default_sync_adapter_registry.register("confluence", ConfluenceConnectorAdapter())
default_sync_adapter_registry.register("google_drive", GoogleDriveConnectorAdapter())
default_sync_adapter_registry.register(
    "microsoft-sharepoint-onedrive",
    MicrosoftSharePointOneDriveConnectorAdapter(),
)
default_sync_adapter_registry.register("notion", NotionConnectorAdapter())
