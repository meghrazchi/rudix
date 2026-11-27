"""Startup reconcile of the configured embedding model with the active generation (R06-08).

Runs after ``init_qdrant`` in the API lifespan, at worker process start, and in
``python -m app.clients.qdrant_bootstrap``. Legacy mode returns at once. In alias mode:

- before adoption: a warning, nothing else (reads and writes stay on QDRANT_COLLECTION);
- configured model and dimension equal the active generation's: nothing to do;
- otherwise a warning (the query path keeps the active generation's model) and, unless a
  building, verifying or retired generation already has the configured model and
  dimension, a new ``building`` generation with its own collection. The active one keeps
  serving; ``scripts/vector_index.py build`` fills the new one.

Concurrent processes may race to register; the unique (alias, generation) constraint
lets one win and the others log and continue.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.vector_index.repositories import generations as repo
from app.domains.vector_index.services import lifecycle_service
from app.domains.vector_index.services.generation_service import configured_alias, registry

logger = get_logger("vector_index")

_PENDING_STATES = ("building", "verifying", "retired")


async def reconcile_on_startup() -> str:
    """Outcome: legacy, not_adopted, current, pending, building_other, registered."""
    alias = configured_alias()
    if alias is None:
        return "legacy"
    rows = await lifecycle_service.list_rows(alias)
    active = repo.pick(rows, ("active",))
    if active is None:
        logger.warning("vector_index.not_adopted", alias=alias)
        return "not_adopted"
    await registry.snapshot(force=True)
    model = settings.openai_embedding_model.strip()
    size = settings.qdrant_vector_size
    distance = settings.qdrant_distance.value
    if (active.embedding_model, active.vector_size, active.distance) == (model, size, distance):
        return "current"
    logger.warning(
        "vector_index.embedding_model_differs",
        alias=alias,
        active_generation=active.generation,
        active_embedding_model=active.embedding_model,
        active_vector_size=active.vector_size,
        configured_embedding_model=model,
        configured_vector_size=size,
    )
    for row in rows:
        if row.state in _PENDING_STATES and (row.embedding_model, row.vector_size) == (
            model,
            size,
        ):
            logger.info(
                "vector_index.generation.pending",
                generation=row.generation,
                state=row.state,
            )
            return "pending"
    if repo.pick(rows, repo.BUILDING_STATES) is not None:
        logger.warning("vector_index.building_other_model", alias=alias)
        return "building_other"
    try:
        await lifecycle_service.register_building(
            embedding_model=model,
            vector_size=size,
            distance=distance,
            reason="startup_config_change",
        )
    except Exception as exc:
        logger.warning("vector_index.registration_failed", error_type=type(exc).__name__)
        registry.invalidate()
        return "pending"
    return "registered"
