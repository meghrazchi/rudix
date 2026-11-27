"""Types and defaults for the worker platform settings (R06-03, R06-04, R06-05; C1).

The fields themselves live in ``WorkersSettings`` after ``# anchor: C1``; this module keeps
their value types, the built-in per-task time limits, and validation helpers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

QueueType = Literal["classic", "quorum"]
WorkerPoolKind = Literal["prefork", "threads"]

# Every hard limit must stay below RabbitMQ's consumer_timeout (default 30 minutes): a
# message unacknowledged for longer is closed by the broker and redelivered while the task
# still runs. The defaults below leave at least one minute of margin to 1800 s.
_LONG = {"soft": 1500, "hard": 1620}


class TaskTimeLimit(BaseModel):
    """Soft and hard time limit of one task, in seconds (``soft`` < ``hard``)."""

    soft: int = Field(ge=1, le=7 * 86_400)
    hard: int = Field(ge=2, le=7 * 86_400)

    @model_validator(mode="after")
    def _soft_below_hard(self) -> TaskTimeLimit:
        if self.soft >= self.hard:
            raise ValueError("a task's soft time limit must be below its hard time limit")
        return self


# Built-in limits per task name. CELERY_TASK_TIME_LIMITS entries merge over these; a task not
# listed uses CELERY_TASK_DEFAULT_SOFT_TIME_LIMIT / CELERY_TASK_DEFAULT_TIME_LIMIT.
DEFAULT_TASK_TIME_LIMITS: dict[str, dict[str, int]] = {
    # Stage tasks (chain mode). Extract runs OCR on whole documents; graph extraction calls
    # the LLM per chunk window and writes Neo4j. Embed embeds and upserts batch by batch and
    # resumes from its last completed batch, so it can be shorter.
    "documents.ingest.extract": dict(_LONG),
    "documents.ingest.clean_detect": {"soft": 600, "hard": 660},
    "documents.ingest.dlp": {"soft": 600, "hard": 660},
    "documents.ingest.chunk": {"soft": 600, "hard": 660},
    "documents.ingest.embed": {"soft": 900, "hard": 960},
    "documents.ingest.index": {"soft": 300, "hard": 360},
    "documents.ingest.finalize": {"soft": 300, "hard": 360},
    "documents.graph_extract": dict(_LONG),
    # Whole-pipeline tasks (inline mode runs every stage inside documents.process).
    "documents.process": dict(_LONG),
    "documents.reindex": dict(_LONG),
    "documents.graph_reindex": dict(_LONG),
    "documents.delete": {"soft": 600, "hard": 660},
    "documents.backfill": {"soft": 600, "hard": 660},
    # Evaluations run a dataset end to end; connector syncs checkpoint per page (D1), so a
    # time-limited run resumes from its checkpoint on retry.
    "evaluations.run": dict(_LONG),
    "safety_evals.run": dict(_LONG),
    "connectors.sync.run": dict(_LONG),
    "maintenance.retention.purge": dict(_LONG),
}


def merge_task_time_limits(value: Any) -> dict[str, TaskTimeLimit]:
    """Built-in defaults overlaid with the configured entries (validated)."""
    merged: dict[str, Any] = {name: dict(limit) for name, limit in DEFAULT_TASK_TIME_LIMITS.items()}
    if value:
        if not isinstance(value, dict):
            raise ValueError("CELERY_TASK_TIME_LIMITS must be a JSON object")
        for name, limit in value.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("CELERY_TASK_TIME_LIMITS keys must be task names")
            merged[name.strip()] = limit
    return {
        name: limit if isinstance(limit, TaskTimeLimit) else TaskTimeLimit.model_validate(limit)
        for name, limit in merged.items()
    }


def parse_queue_list(value: str | None) -> list[str]:
    """Comma-separated queue names, stripped, empty entries and duplicates dropped."""
    if not value:
        return []
    return list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))
