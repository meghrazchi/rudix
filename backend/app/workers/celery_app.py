from celery import Celery  # type: ignore[import-untyped]
from celery.signals import worker_process_init  # type: ignore[import-untyped]
from kombu import Queue  # type: ignore[import-untyped]

from app.clients.neo4j_client import init_neo4j
from app.clients.rabbitmq_client import rabbitmq_broker_url, redis_result_backend_url
from app.core.config import settings
from app.core.logging import configure_logging
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


init_sentry(runtime="worker")
