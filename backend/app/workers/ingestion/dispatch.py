"""Hand-off between the stage tasks of one ingestion run (R06-01 part 2, contract 4.2.4).

``dispatch_stage`` publishes the next stage through the task object's ``apply_async``
(never ``send_task``), so routing comes from ``TASK_ROUTES`` and ``task_always_eager``
runs a whole chain in tests. A publish failure raises ``TransientTaskError``: the current
message is retried (its stage is already completed, so the retry only publishes again).
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.workers.base_task import TransientTaskError
from app.workers.ingestion.stages.base import StageName

logger = get_logger("worker.ingestion")


def stage_task(stage: StageName) -> Any:
    from app.workers.ingestion import tasks

    return tasks.STAGE_TASKS[stage]


def dispatch_stage(stage: StageName, kwargs: dict[str, Any]) -> Any:
    task = stage_task(stage)
    from app.workers.celery_app import celery_app

    if celery_app.conf.task_always_eager:
        # In-process execution (tests): errors of the next stage are its own.
        return task.apply_async(kwargs=kwargs)
    try:
        result = task.apply_async(kwargs=kwargs)
    except Exception as exc:
        logger.warning(
            "ingestion.stage.dispatch_failed",
            stage=str(stage),
            document_id=kwargs.get("document_id"),
            organization_id=kwargs.get("organization_id"),
            run_id=kwargs.get("run_id"),
            error_type=type(exc).__name__,
        )
        raise TransientTaskError(f"publish of {task.name} failed") from exc
    logger.info(
        "ingestion.stage.dispatched",
        stage=str(stage),
        document_id=kwargs.get("document_id"),
        organization_id=kwargs.get("organization_id"),
        run_id=kwargs.get("run_id"),
    )
    return result
