from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from celery import Task  # type: ignore[import-untyped]

from app.core.config import settings
from app.core.logging import get_logger, log_task_failure
from app.core.sentry import bind_sentry_context, capture_sentry_exception
from app.db.tenant_context import bind_worker_tenant

_NON_RETRYABLE_TASK_NAMES: frozenset[str] = frozenset({"documents.delete"})
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def _safe_error_code(exc: Exception) -> str:
    return type(exc).__name__


def _safe_error_message(exc: Exception) -> str:
    raw = str(exc)
    redacted = _UUID_RE.sub("<id>", raw)
    if len(redacted) > 500:
        redacted = redacted[:500] + "…"
    return redacted


def _job_type_from_task_name(task_name: str) -> str:
    mapping = {
        "documents.process": "extraction",
        "documents.delete": "deletion_cleanup",
        "documents.reindex": "reindex",
        "evaluations.run": "evaluation",
        "connectors.sync.run": "connector_sync",
        "connectors.sync.schedule_poll": "connector_sync_schedule",
    }
    return mapping.get(task_name, task_name)


async def _persist_failed_job(
    *,
    task_id: str,
    task_name: str,
    organization_id: str | None,
    document_id: str | None,
    job_id: str | None,
    queue_name: str | None,
    exc: Exception,
    attempt_count: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    from app.db.session import SessionLocal
    from app.models.failed_job import FailedJob

    if not organization_id:
        return

    try:
        org_uuid = UUID(organization_id)
    except ValueError:
        return

    entity_type: str | None = None
    entity_id: UUID | None = None
    if document_id:
        try:
            entity_id = UUID(document_id)
            entity_type = "document"
        except ValueError:
            pass

    is_retryable = task_name not in _NON_RETRYABLE_TASK_NAMES

    # Bound explicitly: on_failure runs outside the task's tenant scope (R06-01 part 2).
    with bind_worker_tenant(org_uuid):
        await _insert_failed_job(
            SessionLocal,
            FailedJob(
                id=uuid4(),
                organization_id=org_uuid,
                task_id=task_id,
                task_name=task_name,
                job_type=_job_type_from_task_name(task_name),
                status="failed",
                queue_name=queue_name,
                error_code=_safe_error_code(exc),
                error_message=_safe_error_message(exc),
                attempt_count=attempt_count,
                is_retryable=is_retryable,
                entity_type=entity_type,
                entity_id=entity_id,
                metadata_json=dict(metadata or {}),
                last_attempted_at=datetime.now(tz=UTC),
                created_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            ),
        )


async def _insert_failed_job(session_factory: Any, job: Any) -> None:
    async with session_factory() as db:
        db.add(job)
        await db.commit()


class TransientTaskError(Exception):
    """Retryable task failure."""


class PermanentTaskError(Exception):
    """Non-retryable task failure."""


class TenantMismatchError(PermanentTaskError):
    """The task's entity belongs to another organisation than its ``organization_id`` kwarg.

    Raised before any write (plan contract 4.2.7). No FailedJob row is written for it and
    no terminal-failure hook runs: either would write into the organisation the message
    named, about an entity of another organisation.
    """

    def __init__(self, message: str = "tenant_mismatch") -> None:
        # The default keeps the exception picklable (Celery stores it by its args).
        super().__init__(message)


class RudixTask(Task):
    abstract = True
    autoretry_for = (TransientTaskError, ConnectionError, TimeoutError, OSError)
    dont_autoretry_for = (PermanentTaskError,)
    retry_backoff = settings.celery_retry_backoff_seconds
    retry_backoff_max = settings.celery_retry_backoff_max_seconds
    retry_jitter = settings.celery_retry_jitter
    max_retries = settings.celery_task_max_retries

    def __init__(self) -> None:
        super().__init__()
        self._logger = get_logger("worker.tasks")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Run the task bound to the tenant of its ``organization_id`` kwarg (contract 4.2.7).

        Every session the task opens then sets ``app.current_organization_id`` for row-level
        security. A task without the kwarg (beat tasks) runs unbound and uses
        ``maintenance_session()`` for cross-tenant work.
        """
        with bind_worker_tenant(kwargs.get("organization_id")):
            return super().__call__(*args, **kwargs)

    def failed_job_identity(
        self, kwargs: dict[str, Any], queue_name: str | None
    ) -> tuple[str, str | None, dict[str, Any]]:
        """Task name, queue, and metadata recorded on this task's FailedJob row."""
        return self.name or "<unknown>", queue_name, {}

    @staticmethod
    def _context(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        document_id = kwargs.get("document_id")
        evaluation_run_id = kwargs.get("evaluation_run_id")
        if document_id is None and args:
            document_id = args[0]
        if evaluation_run_id is None and args:
            evaluation_run_id = args[0]
        return {
            "request_id": kwargs.get("request_id"),
            "organization_id": kwargs.get("organization_id"),
            "user_id": kwargs.get("user_id"),
            "document_id": document_id,
            "job_id": kwargs.get("job_id") or evaluation_run_id,
        }

    def before_start(self, task_id: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        ctx = self._context(args, kwargs)
        bind_sentry_context(
            runtime="worker",
            task_name=self.name,
            task_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
        )
        self._logger.info(
            "task.start",
            task_name=self.name,
            job_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
            document_id=ctx["document_id"],
        )

    def on_success(
        self,
        retval: Any,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        ctx = self._context(args, kwargs)
        bind_sentry_context(
            runtime="worker",
            task_name=self.name,
            task_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
        )
        self._logger.info(
            "task.success",
            task_name=self.name,
            job_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
            document_id=ctx["document_id"],
            status_code="SUCCESS",
        )
        super().on_success(retval, task_id, args, kwargs)

    def on_retry(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        ctx = self._context(args, kwargs)
        bind_sentry_context(
            runtime="worker",
            task_name=self.name,
            task_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
        )
        retries = getattr(self.request, "retries", 0)
        self._logger.warning(
            "task.retry",
            task_name=self.name,
            job_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
            document_id=ctx["document_id"],
            error=exc.__class__.__name__,
            retry_count=retries,
        )
        super().on_retry(exc, task_id, args, kwargs, einfo)

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        from app.workers.async_runtime import run_async

        ctx = self._context(args, kwargs)
        if isinstance(exc, TenantMismatchError):
            self._on_tenant_mismatch(ctx, task_id)
            super().on_failure(exc, task_id, args, kwargs, einfo)
            return
        bind_sentry_context(
            runtime="worker",
            task_name=self.name,
            task_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
        )
        log_task_failure(
            task_name=self.name or "<unknown>",
            job_id=ctx["job_id"] or task_id,
            document_id=ctx["document_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
            error=str(exc),
            request_id=ctx["request_id"],
            exc_info=einfo is not None,
        )
        capture_sentry_exception(
            exc,
            runtime="worker",
            task_name=self.name,
            task_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            user_id=ctx["user_id"],
        )
        task_name, queue_name, metadata = self.failed_job_identity(
            kwargs, (getattr(self.request, "delivery_info", None) or {}).get("routing_key")
        )
        try:
            run_async(
                _persist_failed_job(
                    task_id=task_id,
                    task_name=task_name,
                    organization_id=ctx["organization_id"],
                    document_id=str(ctx["document_id"]) if ctx["document_id"] else None,
                    job_id=ctx["job_id"],
                    queue_name=queue_name,
                    exc=exc,
                    attempt_count=getattr(self.request, "retries", 0) + 1,
                    metadata=metadata,
                )
            )
        except Exception:
            self._logger.warning("failed_job.persist_error", exc_info=True)
        with bind_worker_tenant(ctx["organization_id"]):
            self.on_terminal_failure(exc=exc, args=args, kwargs=kwargs)
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def _on_tenant_mismatch(self, ctx: dict[str, Any], task_id: str) -> None:
        from app.core.metrics_workers import record_worker_tenant_mismatch

        record_worker_tenant_mismatch(self.name or "<unknown>")
        self._logger.warning(
            "task.tenant_mismatch",
            task_name=self.name,
            job_id=ctx["job_id"] or task_id,
            request_id=ctx["request_id"],
            organization_id=ctx["organization_id"],
            document_id=ctx["document_id"],
            error_code="tenant_mismatch",
        )

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """Subclass hook invoked only on terminal failure."""
