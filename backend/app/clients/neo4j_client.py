"""Neo4j async driver for Enterprise Graph (F279).

The driver is only initialized when ENTERPRISE_GRAPH_ENABLED=true. When disabled,
every public function is a safe no-op so that all non-graph Rudix features continue
to operate normally without Neo4j being present or reachable.

Credentials are loaded exclusively from environment variables and are never logged.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger

logger = get_logger("clients.neo4j")

try:
    from neo4j import AsyncDriver, AsyncGraphDatabase  # type: ignore[import-untyped]

    _NEO4J_PACKAGE_AVAILABLE = True
except ImportError:
    _NEO4J_PACKAGE_AVAILABLE = False

_neo4j_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver | None:
    return _neo4j_driver


async def init_neo4j() -> None:
    """Initialize the Neo4j async driver.

    Non-fatal: if Enterprise Graph is disabled, this is a no-op. If enabled but
    the server is unreachable, a warning is logged and Rudix starts normally; the
    health check will report the graph as unavailable.
    """
    global _neo4j_driver

    from app.core.config import settings

    if not settings.enterprise_graph_enabled:
        logger.info("neo4j.init.skipped", reason="enterprise_graph_disabled")
        return

    if not _NEO4J_PACKAGE_AVAILABLE:
        logger.error("neo4j.init.failed", reason="neo4j_package_not_installed")
        return

    uri = settings.neo4j_uri
    username = settings.neo4j_username
    password = settings.neo4j_password.get_secret_value() if settings.neo4j_password else ""

    try:
        _neo4j_driver = AsyncGraphDatabase.driver(
            uri,
            auth=(username, password),
            connection_timeout=settings.neo4j_connection_timeout_seconds,
            max_connection_pool_size=settings.neo4j_max_connection_pool_size,
        )
        await asyncio.wait_for(
            _neo4j_driver.verify_connectivity(),
            timeout=settings.neo4j_connection_timeout_seconds,
        )
        logger.info(
            "neo4j.init.success",
            uri=uri,
            database=settings.neo4j_database,
            pool_size=settings.neo4j_max_connection_pool_size,
        )
    except Exception as exc:
        logger.warning(
            "neo4j.init.unavailable",
            uri=uri,
            error=exc.__class__.__name__,
            detail=str(exc),
        )
        if _neo4j_driver is not None:
            try:
                await _neo4j_driver.close()
            except Exception:
                pass
            _neo4j_driver = None


async def close_neo4j() -> None:
    global _neo4j_driver

    if _neo4j_driver is not None:
        try:
            await _neo4j_driver.close()
        except Exception:
            pass
        _neo4j_driver = None
        logger.info("neo4j.close")


async def check_neo4j_health() -> bool:
    """Return True if the driver is active and a round-trip query succeeds."""
    from app.core.config import settings

    if not settings.enterprise_graph_enabled:
        return True

    if _neo4j_driver is None:
        return False

    try:
        async with _neo4j_driver.session(database=settings.neo4j_database) as session:
            result = await asyncio.wait_for(
                session.run("RETURN 1 AS n"),
                timeout=settings.neo4j_query_timeout_seconds,
            )
            await result.consume()
        return True
    except Exception:
        return False
