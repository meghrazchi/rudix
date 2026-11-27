"""Create or check the Qdrant collection and its payload indexes (R06-07).

``python -m app.clients.qdrant_bootstrap`` runs in the migrate job (``make migrate-qdrant``,
``deploy/scripts/deploy_compose_remote.sh``) next to the database migrations; the API and
the workers run the same check once at startup. The write path no longer does, so a
deployment that changes collection settings or adds a payload index runs this first.
Exit status 0 on success, 1 on failure (the error class is logged, never the API key).
"""

from __future__ import annotations

import sys

from app.clients import qdrant_client as qdrant_module
from app.core.logging import get_logger

logger = get_logger("clients.qdrant")


def bootstrap() -> bool:
    """Initialise the sync client and ensure the collection; True on success."""
    try:
        if qdrant_module.qdrant_client is None:
            qdrant_module.init_qdrant()
        qdrant_module.ensure_qdrant_collection()
    except Exception as exc:
        logger.error("qdrant.bootstrap.failed", error=type(exc).__name__)
        return False
    logger.info("qdrant.bootstrap.completed")
    return True


def main() -> int:
    return 0 if bootstrap() else 1


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
