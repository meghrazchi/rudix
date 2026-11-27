"""Apply Neo4j graph migrations as a deploy step (R04-12).

Exit codes: 0 on success or when the enterprise graph is disabled, 1 on failure.
Run it after ``alembic upgrade head`` in environments where the API does not run
graph migrations on startup (``GRAPH_MIGRATIONS_ON_STARTUP`` defaults to off in
staging and production).
"""

from __future__ import annotations

import asyncio
import sys

from app.clients.neo4j_client import close_neo4j, get_driver, init_neo4j
from app.core.config import settings
from app.core.logging import get_logger
from app.domains.graph.migration_runner import run_graph_migrations

logger = get_logger("scripts.run_graph_migrations")


async def run() -> int:
    if not settings.enterprise_graph_enabled:
        logger.info("graph.migration.script_skipped", reason="enterprise_graph_disabled")
        return 0
    try:
        await init_neo4j()
        if get_driver() is None:
            logger.error("graph.migration.script_failed", error="driver_unavailable")
            return 1
        result = await run_graph_migrations()
    except Exception as exc:
        logger.error("graph.migration.script_failed", error=exc.__class__.__name__)
        return 1
    finally:
        await close_neo4j()
    if not result.success:
        logger.error("graph.migration.script_failed", error=result.failed)
        return 1
    logger.info(
        "graph.migration.script_done",
        applied=len(result.applied),
        already_applied=len(result.already_applied),
    )
    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
