"""Evaluation worker modules, split from ``app.workers.evaluation_tasks`` (R06-12).

``config`` parses the run configuration and thresholds, ``corpus`` prepares the chunking
target corpus, ``question`` runs one question through the query pipeline, ``judge`` is the
LLM judge, ``target`` evaluates one target with bounded concurrency, ``comparison`` builds
summaries and regression flags, ``run`` is ``_run_evaluation_async``, ``tasks`` the Celery
task, and ``collection`` the optional evaluation Qdrant collection.

``app.workers.evaluation_tasks`` stays the facade: tests and callers rebind its module
globals (``SessionLocal``, ``LLMService``, ``_query_retrieval_service``, ...), and every
module here reads those names through ``facade()`` at call time, the pattern of contract
4.2.2 for ``document_tasks``. This package imports nothing heavy at import time, so the
ingestion deletion path can use ``collection`` without an import cycle.
"""

from __future__ import annotations

from types import ModuleType


def facade() -> ModuleType:
    """The ``evaluation_tasks`` module object (imported lazily: it imports this package)."""
    from app.workers import evaluation_tasks

    return evaluation_tasks
