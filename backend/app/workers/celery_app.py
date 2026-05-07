from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun, task_retry

from app.core.config import settings
from app.core.logging import configure_logging, get_logger, log_task_failure

celery_app = Celery(
    "rag_backend",
    broker=str(settings.rabbitmq_url),
    backend=str(settings.redis_url),
    include=[
        "app.workers.document_tasks",
        "app.workers.evaluation_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
)

configure_logging(
    settings.log_level,
    environment=settings.environment.value,
    log_format=settings.log_format.value,
)

worker_logger = get_logger("worker.tasks")


@task_prerun.connect
def on_task_prerun(task_id: str | None = None, task: object | None = None, **_: object) -> None:
    worker_logger.info(
        "task.start",
        task_name=getattr(task, "name", "<unknown>"),
        job_id=task_id,
    )


@task_postrun.connect
def on_task_postrun(
    task_id: str | None = None,
    task: object | None = None,
    state: str | None = None,
    **_: object,
) -> None:
    if state == "SUCCESS":
        worker_logger.info(
            "task.success",
            task_name=getattr(task, "name", "<unknown>"),
            job_id=task_id,
            status_code=state,
        )


@task_retry.connect
def on_task_retry(
    request: object | None = None,
    reason: object | None = None,
    sender: object | None = None,
    **_: object,
) -> None:
    worker_logger.warning(
        "task.retry",
        task_name=getattr(sender, "name", "<unknown>"),
        job_id=getattr(request, "id", None),
        error=str(reason) if reason is not None else None,
    )


@task_failure.connect
def on_task_failure(
    task_id: str | None = None,
    exception: Exception | None = None,
    sender: object | None = None,
    einfo: object | None = None,
    **_: object,
) -> None:
    log_task_failure(
        task_name=getattr(sender, "name", "<unknown>"),
        job_id=task_id,
        error=str(exception) if exception is not None else None,
        exc_info=einfo is not None,
    )
