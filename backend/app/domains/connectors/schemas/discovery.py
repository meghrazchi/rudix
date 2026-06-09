from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConnectorDiscoveredSourceResponse(BaseModel):
    provider_source_id: str = Field(min_length=1, max_length=1024)
    name: str = Field(min_length=1, max_length=512)
    source_type: str = Field(min_length=1, max_length=64)
    source_url: str | None = Field(default=None, max_length=2048)
    parent_provider_source_id: str | None = Field(default=None, max_length=1024)
    metadata: dict[str, Any] = Field(default_factory=dict)
    permissions: dict[str, Any] = Field(default_factory=dict)


class ConnectorDiscoveredSourceListResponse(BaseModel):
    items: list[ConnectorDiscoveredSourceResponse] = Field(default_factory=list)
    total: int = 0
    next_cursor: dict[str, Any] | None = None
    has_more: bool = False
