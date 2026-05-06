from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "rag_backend",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
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
