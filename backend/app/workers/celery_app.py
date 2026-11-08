from time import perf_counter
from typing import Any

from celery import Celery  # type: ignore[import-untyped]
from celery.signals import (  # type: ignore[import-untyped]
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_process_init,
    worker_ready,
)
from kombu import Queue  # type: ignore[import-untyped]

from app.clients.neo4j_client import init_neo4j
from app.clients.rabbitmq_client import rabbitmq_broker_url, redis_result_backend_url
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.metrics import is_metrics_enabled, record_celery_task
from app.core.sentry import init_sentry

celery_app = Celery(
    "rag_backend",
    broker=rabbitmq_broker_url(),
    backend=redis_result_backend_url(),
    include=[
        "app.workers.document_tasks",
        "app.workers.email_tasks",
        "app.workers.evaluation_tasks",
        "app.workers.connector_sync_tasks",
        "app.workers.agent_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    task_default_queue=settings.celery_task_default_queue,
    task_default_exchange="rudix",
    task_default_exchange_type="direct",
    task_default_routing_key=settings.celery_task_default_queue,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    task_publish_retry=True,
    task_publish_retry_policy={
        "max_retries": settings.celery_task_max_retries,
        "interval_start": 0,
        "interval_step": 1,
        "interval_max": settings.celery_retry_backoff_max_seconds,
    },
    task_queues=(
        Queue(
            settings.celery_task_default_queue,
            routing_key=settings.celery_task_default_queue,
        ),
        Queue(
            settings.celery_queue_documents_processing,
            routing_key=settings.celery_queue_documents_processing,
        ),
        Queue(
            settings.celery_queue_documents_deletion,
            routing_key=settings.celery_queue_documents_deletion,
        ),
        Queue(
            settings.celery_queue_documents_reindex,
            routing_key=settings.celery_queue_documents_reindex,
        ),
        Queue(
            settings.celery_queue_evaluations,
            routing_key=settings.celery_queue_evaluations,
        ),
        Queue(
            settings.celery_queue_connector_sync,
            routing_key=settings.celery_queue_connector_sync,
        ),
        Queue("email", routing_key="email"),
    ),
    beat_schedule={
        "connector-sync-schedule-poll": {
            "task": "connectors.sync.schedule_poll",
            "schedule": settings.connector_sync_schedule_poll_interval_seconds,
        },
        "agent-approvals-expire": {
            "task": "agents.approvals.expire",
            "schedule": 60,
        },
    },
    task_routes={
        "documents.process": {
            "queue": settings.celery_queue_documents_processing,
            "routing_key": settings.celery_queue_documents_processing,
        },
        "documents.delete": {
            "queue": settings.celery_queue_documents_deletion,
            "routing_key": settings.celery_queue_documents_deletion,
        },
        "documents.reindex": {
            "queue": settings.celery_queue_documents_reindex,
            "routing_key": settings.celery_queue_documents_reindex,
        },
        "evaluations.run": {
            "queue": settings.celery_queue_evaluations,
            "routing_key": settings.celery_queue_evaluations,
        },
        "connectors.sync.run": {
            "queue": settings.celery_queue_connector_sync,
            "routing_key": settings.celery_queue_connector_sync,
        },
        "connectors.sync.schedule_poll": {
            "queue": settings.celery_queue_connector_sync,
            "routing_key": settings.celery_queue_connector_sync,
        },
        "app.workers.email_tasks.send_transactional_email": {
            "queue": "email",
            "routing_key": "email",
        },
    },
)

configure_logging(
    settings.log_level,
    environment=settings.environment.value,
    log_format=settings.log_format.value,
)


@worker_process_init.connect
def _initialize_worker(*_: object, **__: object) -> None:
    import app.models  # noqa: F401 — ensure all SQLAlchemy mappers are registered

    init_sentry(runtime="worker")
    from app.workers.async_runtime import run_async

    run_async(init_neo4j())


@worker_ready.connect
def _on_worker_ready(*_: object, **__: object) -> None:
    if settings.worker_metrics_enabled:
        try:
            from prometheus_client import start_http_server

            from app.core.metrics import registry

            start_http_server(settings.worker_metrics_port, registry=registry)
        except OSError:
            pass


_task_start_times: dict[str, float] = {}


@task_prerun.connect
def _on_task_prerun(task_id: str, task: Any, *args: object, **kwargs: object) -> None:
    if not is_metrics_enabled():
        return
    _task_start_times[task_id] = perf_counter()
    queue = getattr(task.request, "delivery_info", {}).get("routing_key", "default") or "default"
    record_celery_task(task_name=task.name, queue=queue, status="started")


@task_postrun.connect
def _on_task_postrun(task_id: str, task: Any, state: str, *args: object, **kwargs: object) -> None:
    if not is_metrics_enabled():
        return
    started_at = _task_start_times.pop(task_id, None)
    duration = perf_counter() - started_at if started_at is not None else None
    queue = getattr(task.request, "delivery_info", {}).get("routing_key", "default") or "default"
    record_celery_task(
        task_name=task.name, queue=queue, status=state.lower(), duration_seconds=duration
    )


@task_retry.connect
def _on_task_retry(request: Any, reason: Any, *args: object, **kwargs: object) -> None:
    if not is_metrics_enabled():
        return
    queue = getattr(request, "delivery_info", {}).get("routing_key", "default") or "default"
    task_name = getattr(request, "task", "unknown")
    record_celery_task(task_name=task_name, queue=queue, status="retry")


@task_failure.connect
def _on_task_failure(task_id: str, exception: Any, *args: object, **kwargs: object) -> None:
    if not is_metrics_enabled():
        return
    sender = kwargs.get("sender")
    task_name = getattr(sender, "name", "unknown")
    record_celery_task(task_name=task_name, queue="default", status="failed")


init_sentry(runtime="worker")
