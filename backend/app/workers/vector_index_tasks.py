"""Vector index generation tasks (R06-08).

- ``vector_index.build`` (queue ``CELERY_QUEUE_DOCUMENTS_REINDEX``): runs up to
  ``VECTOR_INDEX_BUILD_MAX_PAGES_PER_TASK`` pages of the build from the generation's
  cursor, then re-enqueues itself until the walk is done and verified. The cursor lives in
  ``vector_index_generations.build_cursor``, so a redelivery, retry, or killed worker
  continues where the last committed document left off. Cross-tenant: it carries no
  ``organization_id``; each document is bound to its own tenant inside the build.
- ``vector_index.drop_retired`` (beat ``vector-index-drop-retired``, daily): deletes
  collections of retired generations past ``QDRANT_RETIRED_GRACE_HOURS``, only when
  ``VECTOR_INDEX_AUTO_DROP_RETIRED`` is true and the alias is configured.

Embedding, Qdrant and usage collaborators are the ingestion worker's
(``app.workers.ingestion.deps.current_deps()``), so tests rebind them in one place.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.vector_index.services import lifecycle_service, reindex_service
from app.domains.vector_index.services.generation_service import configured_alias
from app.workers.async_runtime import run_async
from app.workers.base_task import PermanentTaskError, RudixTask, TransientTaskError
from app.workers.celery_app import celery_app

BUILD_TASK_NAME = "vector_index.build"
DROP_TASK_NAME = "vector_index.drop_retired"

_logger = get_logger("vector_index")


async def run_build(
    *, generation: int | None = None, max_pages: int | None = None
) -> reindex_service.BuildProgress:
    from app.workers.ingestion.deps import current_deps

    deps = current_deps()
    return await reindex_service.build_generation(
        qdrant_service=deps.qdrant_service,
        embedding_service=deps.embedding_service,
        usage_repository=deps.usage_repository,
        generation=generation,
        max_pages=max_pages,
    )


@celery_app.task(name=BUILD_TASK_NAME, bind=True, base=RudixTask, ignore_result=True)
def build_vector_index(
    self: RudixTask, generation: int | None = None, max_pages: int | None = None
) -> dict[str, Any]:
    pages = int(max_pages or settings.vector_index_build_max_pages_per_task)
    try:
        progress = run_async(run_build(generation=generation, max_pages=pages))
    except lifecycle_service.VectorIndexLifecycleError as exc:
        _logger.warning("vector_index.build.skipped", reason=exc.code)
        raise PermanentTaskError(exc.code) from exc
    except reindex_service.VectorIndexBuildError as exc:
        raise TransientTaskError("vector index build document mismatch") from exc
    if not progress.finished:
        build_vector_index.apply_async(
            kwargs={"generation": progress.generation, "max_pages": pages}
        )
    return progress.as_dict()


async def run_drop_retired() -> list[int]:
    return await lifecycle_service.drop_retired(dry_run=False)


@celery_app.task(name=DROP_TASK_NAME, bind=True, base=RudixTask, ignore_result=True)
def drop_retired_vector_indexes(self: RudixTask) -> dict[str, Any]:
    if not settings.vector_index_auto_drop_retired or configured_alias() is None:
        return {"dropped": [], "enabled": False}
    dropped = run_async(run_drop_retired())
    _logger.info("vector_index.drop_retired.completed", dropped=dropped)
    return {"dropped": dropped, "enabled": True}
