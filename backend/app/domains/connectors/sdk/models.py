"""Typed data models for connector SDK: external sources, ACLs, and sync cursors."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExternalSource:
    """Represents a scoped data source within a provider (space, project, drive, channel)."""

    provider_source_id: str
    name: str
    source_type: str
    url: str | None = None
    parent_provider_source_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider_source_id.strip():
            raise ValueError("provider_source_id must not be blank")
        if not self.name.strip():
            raise ValueError("name must not be blank")
        if not self.source_type.strip():
            raise ValueError("source_type must not be blank")


@dataclass
class ExternalACL:
    """Access control entry for an external item.

    Used to build the ACL hash and permissions dict on NormalizedExternalItem.
    """

    principal_type: str  # "user" | "group" | "role" | "anyone"
    principal_id: str
    access_level: str  # "read" | "write" | "admin" | "none"
    inherited: bool = False

    def __post_init__(self) -> None:
        allowed_principal_types = {"user", "group", "role", "anyone"}
        if self.principal_type not in allowed_principal_types:
            raise ValueError(f"principal_type must be one of {allowed_principal_types!r}")
        allowed_access_levels = {"read", "write", "admin", "none"}
        if self.access_level not in allowed_access_levels:
            raise ValueError(f"access_level must be one of {allowed_access_levels!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "principal_type": self.principal_type,
            "principal_id": self.principal_id,
            "access_level": self.access_level,
            "inherited": self.inherited,
        }


@dataclass
class SyncCursor:
    """Typed wrapper around the opaque cursor dict used by the sync engine.

    Adapters interact with the cursor via typed accessors rather than raw dict
    access so that missing keys surface as clear errors rather than silent None.
    """

    _data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncCursor:
        return cls(_data=dict(data))

    @classmethod
    def empty(cls) -> SyncCursor:
        return cls(_data={})

    def is_empty(self) -> bool:
        return not self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def require(self, key: str) -> Any:
        if key not in self._data:
            raise KeyError(f"cursor is missing required key {key!r}")
        return self._data[key]

    def set(self, key: str, value: Any) -> SyncCursor:
        """Return a new cursor with key set (immutable update)."""
        new_data = {**self._data, key: value}
        return SyncCursor(_data=new_data)

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def is_json_serializable(self) -> bool:
        try:
            json.dumps(self._data)
            return True
        except (TypeError, ValueError):
            return False

    def __repr__(self) -> str:
        return f"SyncCursor({self._data!r})"
