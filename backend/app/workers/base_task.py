from __future__ import annotations

from typing import Any

from celery import Task  # type: ignore[import-untyped]

from app.core.config import settings
from app.core.logging import get_logger, log_task_failure
from app.core.sentry import bind_sentry_context, capture_sentry_exception


class TransientTaskError(Exception):
    """Retryable task failure."""


class PermanentTaskError(Exception):
    """Non-retryable task failure."""


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
        ctx = self._context(args, kwargs)
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
        self.on_terminal_failure(exc=exc, args=args, kwargs=kwargs)
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_terminal_failure(
        self,
        *,
        exc: Exception,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        """Subclass hook invoked only on terminal failure."""
