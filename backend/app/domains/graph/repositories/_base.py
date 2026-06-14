"""Shared helpers for graph repositories (F281).

All repositories must call _get_driver_and_settings() and bail out if None
is returned — this covers both disabled-feature and driver-unavailable cases
so that Neo4j outages do not break non-graph Rudix flows.
"""

from __future__ import annotations

from typing import Any

from app.clients.neo4j_client import get_driver
from app.core.logging import get_logger

logger = get_logger("graph.repositories")


def _get_driver_and_settings() -> tuple[Any, Any] | tuple[None, None]:
    """Return (driver, settings) or (None, None) when graph is unavailable."""
    from app.core.config import settings

    if not settings.enterprise_graph_enabled:
        return None, None
    driver = get_driver()
    if driver is None:
        return None, None
    return driver, settings
