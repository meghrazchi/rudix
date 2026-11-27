"""Task time limits, child recycling, and the consumer-timeout check (R06-03; C1).

Per-task limits go through ``task_annotations`` keyed by task name; the defaults go through
``task_soft_time_limit`` / ``task_time_limit``. A ``"*"`` annotation is not used: Celery
applies the ``"*"`` entry after the per-name entry (``celery/app/annotations.py``), so it
would overwrite every specific limit.

RabbitMQ closes the channel of a consumer that holds an unacknowledged delivery longer than
its ``consumer_timeout`` and redelivers the message. With ``acks_late`` the ack comes after
the task returns, so every hard limit must stay below that timeout.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.core.config import Settings

logger = get_logger("worker.time_limits")

SOFT_TIME_LIMIT_ERROR_CODE = "task_soft_time_limit"
HARD_TIME_LIMIT_ERROR_CODE = "task_time_limit"
_STRICT_ENVIRONMENTS = frozenset({"production", "staging"})


class ConsumerTimeoutConfigError(ValueError):
    """A configured hard time limit is not below the broker consumer timeout."""


def build_task_annotations(config: Settings) -> dict[str, dict[str, int]]:
    return {
        name: {"soft_time_limit": limit.soft, "time_limit": limit.hard}
        for name, limit in sorted(config.celery_task_time_limits.items())
    }


def time_limit_conf(config: Settings) -> dict[str, Any]:
    """Celery configuration keys for limits and recycling (0 means off for recycling)."""
    return {
        "task_soft_time_limit": config.celery_task_default_soft_time_limit,
        "task_time_limit": config.celery_task_default_time_limit,
        "task_annotations": build_task_annotations(config),
        "worker_max_tasks_per_child": config.celery_worker_max_tasks_per_child or None,
        "worker_max_memory_per_child": config.celery_worker_max_memory_per_child_kb or None,
    }


def hard_limits_over_consumer_timeout(config: Settings) -> list[tuple[str, int]]:
    """(task name or ``<default>``, hard limit) pairs that are not below the timeout."""
    timeout = config.celery_broker_consumer_timeout_seconds
    limits = [("<default>", config.celery_task_default_time_limit)]
    limits.extend((name, limit.hard) for name, limit in config.celery_task_time_limits.items())
    return sorted((name, hard) for name, hard in limits if hard >= timeout)


def check_consumer_timeout(config: Settings) -> None:
    """Raise in production and staging, warn elsewhere, when a hard limit reaches the timeout."""
    offending = hard_limits_over_consumer_timeout(config)
    if not offending:
        return
    timeout = config.celery_broker_consumer_timeout_seconds
    tasks = ", ".join(f"{name}={hard}s" for name, hard in offending)
    if config.environment.value in _STRICT_ENVIRONMENTS:
        logger.error(
            "worker.time_limit_exceeds_consumer_timeout",
            consumer_timeout_seconds=timeout,
            tasks=tasks,
        )
        raise ConsumerTimeoutConfigError(
            f"hard time limits must be below CELERY_BROKER_CONSUMER_TIMEOUT_SECONDS "
            f"({timeout}s): {tasks}"
        )
    logger.warning(
        "worker.time_limit_exceeds_consumer_timeout",
        consumer_timeout_seconds=timeout,
        tasks=tasks,
    )


def time_limit_error_code(exc: BaseException) -> str | None:
    """``task_soft_time_limit`` / ``task_time_limit`` for Celery's limit exceptions."""
    from celery.exceptions import (  # type: ignore[import-untyped]
        SoftTimeLimitExceeded,
        TimeLimitExceeded,
    )

    if isinstance(exc, SoftTimeLimitExceeded):
        return SOFT_TIME_LIMIT_ERROR_CODE
    if isinstance(exc, TimeLimitExceeded):
        return HARD_TIME_LIMIT_ERROR_CODE
    return None
