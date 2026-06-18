"""Abstract interface for per-source-type authorization adapters — F332.

Any new source or resource type that exposes content through Rudix MUST implement
this interface before the policy engine can grant access to its resources. Unknown
types fall through to ResourceType.unknown, which always results in a deny (rule 4
of the precedence chain).

Usage — registering a new source type:

    from app.auth.source_authorization_adapter import SourceAuthorizationAdapter, registry

    class MySourceAdapter(SourceAuthorizationAdapter):
        source_type = "my_source"

        async def build_resource_context(self, ...):
            ...

    registry.register(MySourceAdapter())
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.policy_engine import ResourceContext, ResourceType


class SourceAuthorizationAdapter(ABC):
    """Per-source authorization adapter.

    Implementors must set ``source_type`` to a canonical lowercase string that
    matches the ``resource_type`` field stored on source documents.
    """

    source_type: ClassVar[str]

    @abstractmethod
    async def build_resource_context(
        self,
        db_session: AsyncSession,
        *,
        resource_id: str,
        organization_id: str,
        subject_accessible_collection_ids: list[str],
    ) -> ResourceContext:
        """Resolve all ACL data for a single resource and return a ResourceContext.

        Implementations must:
        - Return ``ResourceType.unknown`` when the resource cannot be found or
          has no registered adapter — this triggers a deny at rule 4.
        - Never raise; catch internal errors and fall back to a default-deny context.
        """
        ...

    def default_deny_context(
        self,
        *,
        resource_id: str,
        organization_id: str,
    ) -> ResourceContext:
        """Return a context that always results in deny (unknown resource type)."""
        return ResourceContext(
            resource_type=ResourceType.unknown,
            resource_id=resource_id,
            organization_id=organization_id,
        )


class SourceAuthorizationAdapterRegistry:
    """Thread-safe registry mapping source_type strings to adapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[str, SourceAuthorizationAdapter] = {}

    def register(self, adapter: SourceAuthorizationAdapter) -> None:
        self._adapters[adapter.source_type] = adapter

    def get(self, source_type: str) -> SourceAuthorizationAdapter | None:
        return self._adapters.get(source_type)

    def get_or_default_deny(self, source_type: str) -> SourceAuthorizationAdapter:
        """Return the registered adapter or a default-deny stub."""
        adapter = self._adapters.get(source_type)
        if adapter is not None:
            return adapter
        return _DefaultDenyAdapter(source_type=source_type)

    def registered_types(self) -> list[str]:
        return list(self._adapters.keys())


class _DefaultDenyAdapter(SourceAuthorizationAdapter):
    """Sentinel adapter for unregistered source types — always returns deny context."""

    def __init__(self, *, source_type: str) -> None:
        self._source_type = source_type

    @property
    def source_type(self) -> str:  # type: ignore[override]
        return self._source_type

    async def build_resource_context(
        self,
        db_session: AsyncSession,
        *,
        resource_id: str,
        organization_id: str,
        subject_accessible_collection_ids: list[str],
    ) -> ResourceContext:
        return self.default_deny_context(
            resource_id=resource_id, organization_id=organization_id
        )


# Global registry — adapters register themselves at import time.
registry = SourceAuthorizationAdapterRegistry()
