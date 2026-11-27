"""Connector framework settings."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    field_validator,
)
from pydantic_settings import NoDecode

from app.core.settings.enums import (
    ConnectorOAuthClientSettings,
    ConnectorRolloutStage,
)

if TYPE_CHECKING:
    from app.core.config import Settings


class ConnectorsSettings(BaseModel):
    connector_sync_schedule_poll_interval_seconds: int = Field(default=60, ge=10, le=3600)
    connector_credential_encryption_key: SecretStr | None = None
    connector_credential_encryption_key_id: str = Field(
        default="default",
        min_length=1,
        max_length=128,
        pattern=r"^[a-zA-Z0-9._:-]+$",
    )
    connector_oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    connector_oauth_clients: Annotated[list[ConnectorOAuthClientSettings], NoDecode] = Field(
        default_factory=list
    )
    feature_enable_connectors: bool = True
    connector_rollout_stage: ConnectorRolloutStage = ConnectorRolloutStage.all

    @field_validator("connector_oauth_clients", mode="before")
    @classmethod
    def validate_connector_oauth_clients(
        cls, value: object
    ) -> list[ConnectorOAuthClientSettings] | list[dict[str, Any]]:
        if value is None:
            return []
        raw_items: list[object]
        if isinstance(value, str):
            normalized_text = value.strip()
            if not normalized_text:
                return []
            try:
                parsed = json.loads(normalized_text)
            except json.JSONDecodeError as exc:
                raise ValueError("connector_oauth_clients must be valid JSON") from exc
            if not isinstance(parsed, list):
                raise ValueError("connector_oauth_clients JSON value must be an array")
            raw_items = list(parsed)
        elif isinstance(value, list):
            raw_items = list(value)
        else:
            raise ValueError("connector_oauth_clients must be a JSON array or list")

        normalized_items: list[ConnectorOAuthClientSettings] = []
        seen_providers: set[str] = set()
        for item in raw_items:
            client_config = ConnectorOAuthClientSettings.model_validate(item)
            if client_config.provider_key in seen_providers:
                raise ValueError(
                    f"duplicate connector OAuth provider_key: {client_config.provider_key}"
                )
            seen_providers.add(client_config.provider_key)
            normalized_items.append(client_config)
        return normalized_items


def validate_connector_rollout(settings: Settings) -> None:
    if settings.connector_rollout_stage == ConnectorRolloutStage.off:
        settings.feature_enable_connectors = False
