"""RabbitMQ and Celery worker settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import (
    AmqpDsn,
    BaseModel,
    Field,
    field_validator,
)

if TYPE_CHECKING:
    pass


class CelerySettings(BaseModel):
    rabbitmq_url: AmqpDsn
    rabbitmq_connect_timeout_seconds: float = Field(default=2.0, ge=0.1, le=30.0)
    celery_result_backend_enabled: bool = True
    celery_task_default_queue: str = Field(default="default", min_length=1, max_length=64)
    celery_queue_documents_processing: str = Field(
        default="documents.processing", min_length=1, max_length=64
    )
    celery_queue_documents_deletion: str = Field(
        default="documents.deletion", min_length=1, max_length=64
    )
    celery_queue_documents_reindex: str = Field(
        default="documents.reindex", min_length=1, max_length=64
    )
    celery_queue_evaluations: str = Field(default="evaluations", min_length=1, max_length=64)
    celery_queue_connector_sync: str = Field(default="connectors.sync", min_length=1, max_length=64)
    celery_task_max_retries: int = Field(default=5, ge=0, le=20)
    celery_retry_backoff_seconds: int = Field(default=2, ge=1, le=300)
    celery_retry_backoff_max_seconds: int = Field(default=60, ge=1, le=3600)
    celery_retry_jitter: bool = True
    celery_worker_prefetch_multiplier: int = Field(default=1, ge=1, le=20)
    document_processing_stale_seconds: int = Field(default=3600, ge=300, le=86400)
    document_reaper_interval_seconds: int = Field(default=300, ge=30, le=3600)
    document_reaper_max_attempts: int = Field(default=3, ge=1, le=20)
    document_reaper_batch_size: int = Field(default=100, ge=1, le=1000)
    evaluation_prevent_duplicate_active_runs: bool = True

    @field_validator(
        "celery_task_default_queue",
        "celery_queue_documents_processing",
        "celery_queue_documents_deletion",
        "celery_queue_documents_reindex",
        "celery_queue_evaluations",
        "celery_queue_connector_sync",
    )
    @classmethod
    def validate_celery_queue_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("celery queue names must not be empty")
        if not cleaned.replace(".", "").replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "celery queue names may contain only letters, numbers, '.', '-', and '_'"
            )
        return cleaned
