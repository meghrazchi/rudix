from time import perf_counter
from typing import Any

from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]
from celery.signals import (  # type: ignore[import-untyped]
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
    worker_init,
    worker_process_init,
    worker_ready,
)

from app.clients.neo4j_client import init_neo4j
from app.clients.rabbitmq_client import rabbitmq_broker_url, redis_result_backend_url
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.metrics import is_metrics_enabled, record_celery_task
from app.core.sentry import init_sentry
from app.workers.dead_letter import install_worker_bootsteps
from app.workers.queues import build_task_queues, queue_conf
from app.workers.time_limits import (
    ConsumerTimeoutConfigError,
    check_consumer_timeout,
    time_limit_conf,
)


def _route(queue: str) -> dict[str, str]:
    return {"queue": queue, "routing_key": queue}


# Task modules. Later work packages add theirs directly after their marker.
INCLUDE: list[str] = [
    "app.workers.document_tasks",
    "app.workers.document_reaper_tasks",
    "app.workers.email_tasks",
    "app.workers.evaluation_tasks",
    "app.workers.connector_sync_tasks",
    "app.workers.agent_tasks",
    "app.workers.usage_touch_tasks",
    "app.workers.safety_eval_tasks",
    "app.workers.retention_tasks",
    # anchor: S2
    "app.workers.ingestion.tasks",
    "app.workers.outbox_tasks",
    # anchor: A2
    # anchor: A3
    # anchor: B1
    # anchor: C1
    # anchor: C2
    # anchor: D1
]

# Stage tasks of the staged ingestion chain (R06-01): extract..chunk on the processing
# queue, embed/index/finalize on the embedding queue, graph extraction on its own queue.
_INGEST_PROCESSING_STAGES = ("extract", "clean_detect", "dlp", "chunk")
_INGEST_EMBEDDING_STAGES = ("embed", "index", "finalize")

TASK_ROUTES: dict[str, dict[str, str]] = {
    "documents.process": _route(settings.celery_queue_documents_processing),
    "documents.delete": _route(settings.celery_queue_documents_deletion),
    "documents.reindex": _route(settings.celery_queue_documents_reindex),
    "evaluations.run": _route(settings.celery_queue_evaluations),
    "connectors.sync.run": _route(settings.celery_queue_connector_sync),
    "connectors.sync.schedule_poll": _route(settings.celery_queue_connector_sync),
    "documents.graph_reindex": _route(settings.celery_queue_documents_reindex),
    "documents.backfill": _route(settings.celery_queue_documents_reindex),
    "safety_evals.run": _route(settings.celery_queue_evaluations),
    "agents.approvals.expire": _route(settings.celery_task_default_queue),
    "usage.touch.flush": _route(settings.celery_task_default_queue),
    "documents.reap_stale": _route(settings.celery_task_default_queue),
    "maintenance.retention.purge": _route(settings.celery_task_default_queue),
    "maintenance.partitions.ensure": _route(settings.celery_task_default_queue),
    "app.workers.email_tasks.send_transactional_email": _route(settings.celery_queue_email),
    # anchor: S2
    **{
        f"documents.ingest.{stage}": _route(settings.celery_queue_documents_processing)
        for stage in _INGEST_PROCESSING_STAGES
    },
    **{
        f"documents.ingest.{stage}": _route(settings.celery_queue_documents_embedding)
        for stage in _INGEST_EMBEDDING_STAGES
    },
    "documents.graph_extract": _route(settings.celery_queue_documents_graph),
    "outbox.relay": _route(settings.celery_task_default_queue),
    "documents.stage_artifacts.purge": _route(settings.celery_task_default_queue),
    # anchor: A2
    # anchor: A3
    # anchor: B1
    # anchor: C1
    # anchor: C2
    "agents.run.execute": _route(settings.celery_queue_agents),
    "agents.run.resume": _route(settings.celery_queue_agents),
    "agents.runs.reap": _route(settings.celery_task_default_queue),
    # anchor: D1
}

BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "connector-sync-schedule-poll": {
        "task": "connectors.sync.schedule_poll",
        "schedule": settings.connector_sync_schedule_poll_interval_seconds,
    },
    "agent-approvals-expire": {
        "task": "agents.approvals.expire",
        "schedule": 60,
    },
    "usage-touch-flush": {
        "task": "usage.touch.flush",
        "schedule": settings.usage_touch_flush_interval_seconds,
    },
    "documents-reap-stale": {
        "task": "documents.reap_stale",
        "schedule": settings.document_reaper_interval_seconds,
    },
    "maintenance-retention-purge": {
        "task": "maintenance.retention.purge",
        "schedule": crontab(hour=3, minute=15),
    },
    "maintenance-partitions-ensure": {
        "task": "maintenance.partitions.ensure",
        "schedule": crontab(hour=3, minute=45),
    },
    # anchor: S2
    "outbox-relay": {
        "task": "outbox.relay",
        "schedule": settings.outbox_relay_interval_seconds,
    },
    "documents-stage-artifacts-purge": {
        "task": "documents.stage_artifacts.purge",
        "schedule": crontab(hour=4, minute=5),
    },
    # anchor: A2
    # anchor: A3
    # anchor: B1
    # anchor: C1
    # anchor: C2
    "agents-runs-reap": {
        "task": "agents.runs.reap",
        "schedule": settings.agent_run_reap_interval_seconds,
    },
    # anchor: D1
}


celery_app = Celery(
    "rag_backend",
    broker=rabbitmq_broker_url(),
    backend=redis_result_backend_url(),
    include=INCLUDE,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    task_default_queue=settings.celery_task_default_queue,
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
    # anchor: C1 (queue declarations, limits, recycling; R06-03, R06-05)
    task_queues=build_task_queues(settings),
    **queue_conf(settings),
    **time_limit_conf(settings),
    beat_schedule=BEAT_SCHEDULE,
    task_routes=TASK_ROUTES,
)

configure_logging(
    settings.log_level,
    environment=settings.environment.value,
    log_format=settings.log_format.value,
)


install_worker_bootsteps(celery_app)
import app.workers.queue_metrics  # noqa: E402,F401 — connects the queue wait signals


@worker_init.connect
def _check_worker_limits(*_: object, **__: object) -> None:
    """Refuse to start (production, staging) when a hard limit reaches the consumer timeout.

    Celery logs and swallows ``Exception`` from signal handlers; ``SystemExit`` stops it.
    """
    try:
        check_consumer_timeout(settings)
    except ConsumerTimeoutConfigError as exc:
        raise SystemExit(str(exc)) from exc


@worker_process_init.connect
def _initialize_worker(*_: object, **__: object) -> None:
    import app.models  # noqa: F401 — ensure all SQLAlchemy mappers are registered

    init_sentry(runtime="worker")
    from app.workers.async_runtime import reset_worker_loop_after_fork, run_async

    # A child forked after the main process used the database or an event loop (dead-letter
    # consumer, hard time-limit on_failure, child recycling) must not share them (R06-03).
    reset_worker_loop_after_fork()
    from app.db.session import engine

    run_async(engine.dispose(close=False))
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
