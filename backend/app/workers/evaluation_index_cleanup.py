"""Removes the chunks and vectors an evaluation run re-ingested under an ``eval-`` version.

Chunking comparisons re-ingest documents into the shared Qdrant collection and
``document_chunks`` table under ``eval-<run hex10>-<n>``. Production retrieval filters on
the active index versions, so those rows are invisible to chat, but they still take space
and must be removed once the run no longer needs them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import record_eval_index_cleanup_failure
from app.db.session import SessionLocal
from app.domains.documents.repositories.documents import DocumentRepository
from app.workers import document_tasks

EVAL_INDEX_VERSION_PREFIX = "eval-"

logger = get_logger("evaluation.index_cleanup")


@dataclass(frozen=True)
class EvalIndexCleanupResult:
    index_version: str
    documents_attempted: int
    chunks_deleted: int
    qdrant_failures: int
    chunk_failures: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def is_eval_index_version(index_version: str | None) -> bool:
    return bool(index_version) and str(index_version).startswith(EVAL_INDEX_VERSION_PREFIX)


def _ensure_deletable(index_version: str) -> None:
    if not is_eval_index_version(index_version):
        raise ValueError("only eval- index versions can be cleaned up")
    if index_version in settings.active_index_versions:
        raise ValueError("refusing to clean up an active index version")


async def cleanup_eval_index_version_async(
    *,
    organization_id: UUID,
    document_ids: Sequence[UUID],
    index_version: str,
) -> EvalIndexCleanupResult:
    _ensure_deletable(index_version)
    repository = DocumentRepository()
    chunks_deleted = 0
    qdrant_failures = 0
    chunk_failures = 0

    for document_id in document_ids:
        try:
            # Looked up at call time so tests can monkeypatch document_tasks._qdrant_service.
            await document_tasks._qdrant_service.delete_document_points(
                organization_id=organization_id,
                document_id=document_id,
                index_version=index_version,
            )
        except Exception as exc:
            qdrant_failures += 1
            record_eval_index_cleanup_failure(store="qdrant")
            logger.warning(
                "evaluation.index_cleanup.qdrant_failed",
                organization_id=str(organization_id),
                document_id=str(document_id),
                index_version=index_version,
                error_type=exc.__class__.__name__,
            )

        async with SessionLocal() as session:
            try:
                chunks_deleted += await repository.delete_document_chunks(
                    session,
                    document_id=document_id,
                    index_version=index_version,
                )
                await session.commit()
            except Exception as exc:
                await session.rollback()
                chunk_failures += 1
                record_eval_index_cleanup_failure(store="postgres")
                logger.warning(
                    "evaluation.index_cleanup.chunks_failed",
                    organization_id=str(organization_id),
                    document_id=str(document_id),
                    index_version=index_version,
                    error_type=exc.__class__.__name__,
                )

    return EvalIndexCleanupResult(
        index_version=index_version,
        documents_attempted=len(document_ids),
        chunks_deleted=chunks_deleted,
        qdrant_failures=qdrant_failures,
        chunk_failures=chunk_failures,
    )
