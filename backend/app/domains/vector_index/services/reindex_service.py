"""Background build of a vector index generation (R06-08).

``build_generation`` walks indexed documents of every organisation by
``(organization_id, document_id)`` from the generation's ``build_cursor``. Per document,
bound to its tenant:

1. read the embeddable chunk rows of the active index versions from Postgres (no
   re-extraction) in batches of ``INGEST_EMBED_BATCH_CHUNKS``;
2. reuse vectors already in the target collection, embed the rest with the generation's
   model, and upsert them into the target collection (deterministic point ids);
3. delete the document's other points in the target and count what is left;
4. in one transaction: the ``vector_index_generation_documents`` row (point count), the
   ``document.embedding`` usage event when tokens were spent (``reason=vector_reindex``),
   and the cursor.

A kill anywhere before step 4 leaves the document without a row and the cursor before it,
so a rerun redoes only that document; upserts replace the same point ids, so nothing is
duplicated. A document that already has a row (dual write, earlier run) is skipped.
When the walk finishes, the generation is verified (``lifecycle_service.verify``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics_workers import record_reindex_progress
from app.db.session import maintenance_session
from app.db.tenant_context import tenant_context_scope
from app.domains.vector_index.repositories import generations as repo
from app.domains.vector_index.services import lifecycle_service
from app.domains.vector_index.services.generation_service import GenerationTarget, to_target
from app.domains.vector_index.services.target_writer import write_rows
from app.models.document import DocumentChunk

logger = get_logger("vector_index")


class VectorIndexBuildError(RuntimeError):
    """A document whose points in the target do not match its chunk rows (transient)."""


@dataclass
class BuildProgress:
    generation: int
    cursor: tuple[UUID, UUID] | None
    pages: int = 0
    documents_written: int = 0
    documents_skipped: int = 0
    finished: bool = False
    verify: lifecycle_service.VerifyResult | None = None
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "cursor": cursor_to_json(self.cursor),
            "pages": self.pages,
            "documents_written": self.documents_written,
            "documents_skipped": self.documents_skipped,
            "finished": self.finished,
            "verified": None if self.verify is None else self.verify.passed,
        }


def build_marker(generation: int) -> str:
    """``ingest_run_id`` of points the build writes (stale cleanup keeps only these)."""
    return f"vector-index-g{int(generation)}"


def cursor_to_json(cursor: tuple[UUID, UUID] | None) -> dict[str, str] | None:
    if cursor is None:
        return None
    return {"organization_id": str(cursor[0]), "document_id": str(cursor[1])}


def cursor_from_json(value: Any) -> tuple[UUID, UUID] | None:
    if not isinstance(value, dict):
        return None
    try:
        return UUID(str(value["organization_id"])), UUID(str(value["document_id"]))
    except (KeyError, ValueError):
        return None


def _session() -> Any:
    from app.db import session as db_session_module

    return db_session_module.SessionLocal()


async def _start(generation: int | None) -> Any:
    alias = lifecycle_service.require_alias()
    rows = await lifecycle_service.list_rows(alias)
    if generation is not None:
        row = next((r for r in rows if r.generation == generation), None)
    else:
        row = repo.pick(rows, (*repo.BUILDING_STATES, "failed"))
    if row is None:
        raise lifecycle_service.VectorIndexLifecycleError("nothing_to_build")
    if row.state == "failed":
        # A failed verify reruns the walk from the start; documents with a row are skipped.
        await lifecycle_service.set_state(
            row.id, state="building", error_code=None, build_cursor=None
        )
        row.state, row.build_cursor = "building", None
    elif row.state == "verifying":
        await lifecycle_service.set_state(row.id, state="building")
        row.state = "building"
    if row.state != "building":
        raise lifecycle_service.VectorIndexLifecycleError("not_building")
    return row


async def _read_rows(document_id: UUID) -> tuple[list[Any], dict[UUID, str]]:
    async with _session() as session:
        rows = list(
            (
                await session.execute(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.document_id == document_id,
                        DocumentChunk.index_version.in_(list(settings.active_index_versions)),
                        DocumentChunk.qdrant_point_id.is_not(None),
                    )
                    .order_by(DocumentChunk.index_version, DocumentChunk.chunk_index)
                )
            ).scalars()
        )
        parent_ids = {row.parent_chunk_id for row in rows if row.parent_chunk_id is not None}
        parents: dict[UUID, str] = {}
        if parent_ids:
            found = await session.execute(
                select(DocumentChunk.id, DocumentChunk.text).where(
                    DocumentChunk.id.in_(list(parent_ids))
                )
            )
            parents = {pid: str(text) for pid, text in found}
        session.expunge_all()
    by_child = {
        row.id: parents[row.parent_chunk_id]
        for row in rows
        if row.parent_chunk_id is not None and row.parent_chunk_id in parents
    }
    return rows, by_child


async def _has_row(generation_id: UUID, document_id: UUID) -> bool:
    async with _session() as session:
        return await repo.generation_has_document(
            session, generation_id=generation_id, document_id=document_id
        )


async def _count_target(qdrant_service: Any, target: GenerationTarget, document: Any) -> int:
    total = 0
    for version in settings.active_index_versions:
        kwargs = {
            "organization_id": document.organization_id,
            "document_id": document.id,
            "index_version": version,
            "collection_name": target.collection_name,
        }
        await qdrant_service.delete_stale_document_points(
            **kwargs, ingest_run_id=build_marker(int(target.generation or 0))
        )
        total += int(await qdrant_service.count_document_points(**kwargs))
    return total


async def _build_document(
    *,
    target: GenerationTarget,
    document: Any,
    qdrant_service: Any,
    embedding_service: Any,
    usage_repository: Any,
) -> bool:
    """Write one document into the target; False when it already had a row."""
    assert target.generation_id is not None
    with tenant_context_scope(document.organization_id):
        if await _has_row(target.generation_id, document.id):
            return False
        rows, parents = await _read_rows(document.id)
        size = settings.ingest_embed_batch_chunks
        input_tokens = total_tokens = 0
        cost = Decimal("0")
        for start in range(0, len(rows), size):
            batch = rows[start : start + size]
            batch_ids = {row.id for row in batch}
            write = await write_rows(
                qdrant_service=qdrant_service,
                embedding_service=embedding_service,
                target=target,
                document=document,
                rows=batch,
                parent_text={k: v for k, v in parents.items() if k in batch_ids},
                ingest_run_id=build_marker(int(target.generation or 0)),
            )
            input_tokens += write.input_tokens
            total_tokens += write.total_tokens
            cost += write.cost
        points = await _count_target(qdrant_service, target, document)
        if points != len(rows):
            raise VectorIndexBuildError(
                f"generation {target.generation} holds {points} points for a document "
                f"with {len(rows)} chunk rows"
            )
        async with _session() as session, session.begin():
            await repo.record_generation_document(
                session,
                generation_id=target.generation_id,
                organization_id=document.organization_id,
                document_id=document.id,
                point_count=points,
            )
            if total_tokens > 0:
                await usage_repository.create_usage_event(
                    session,
                    organization_id=document.organization_id,
                    user_id=document.uploaded_by_user_id,
                    event_type="document.embedding",
                    model_name=target.embedding_model,
                    input_tokens=input_tokens,
                    output_tokens=None,
                    cost_usd=cost,
                    metadata={
                        "reason": "vector_reindex",
                        "generation": target.generation,
                        "document_id": str(document.id),
                        "chunk_count": len(rows),
                        "total_tokens": total_tokens,
                    },
                )
            await repo.set_build_cursor(
                session,
                generation_id=target.generation_id,
                cursor=cursor_to_json((document.organization_id, document.id)) or {},
            )
    return True


async def refresh_progress(generation_id: UUID) -> tuple[int, int]:
    """Recount documents_done and indexed_points across organisations; set the gauge."""
    async with maintenance_session() as session:
        total = await repo.count_indexed_documents(session)
        done, points = await repo.generation_progress(session, generation_id=generation_id)
        await session.rollback()
    async with _session() as session, session.begin():
        row = await repo.get_by_id(session, generation_id)
        if row is not None:
            row.documents_total, row.documents_done, row.indexed_points = total, done, points
            record_reindex_progress(int(row.generation), done, total)
    return done, total


async def build_generation(
    *,
    qdrant_service: Any,
    embedding_service: Any,
    usage_repository: Any,
    generation: int | None = None,
    max_pages: int | None = None,
) -> BuildProgress:
    """Run pages of the build from the cursor; verify when the walk is complete."""
    row = await _start(generation)
    target = to_target(row)
    progress = BuildProgress(generation=row.generation, cursor=cursor_from_json(row.build_cursor))
    logger.info(
        "vector_index.build.started",
        generation=row.generation,
        collection=row.collection_name,
        resumed=progress.cursor is not None,
    )
    page_size = settings.vector_index_build_batch_documents
    while max_pages is None or progress.pages < max_pages:
        async with maintenance_session() as session:
            page = await repo.documents_page(session, after=progress.cursor, limit=page_size)
            await session.rollback()
        if not page:
            progress.finished = True
            break
        for document in page:
            written = await _build_document(
                target=target,
                document=_DocumentRef.from_row(document),
                qdrant_service=qdrant_service,
                embedding_service=embedding_service,
                usage_repository=usage_repository,
            )
            progress.cursor = (document.organization_id, document.id)
            if written:
                progress.documents_written += 1
            else:
                progress.documents_skipped += 1
        async with _session() as session, session.begin():
            await repo.set_build_cursor(
                session, generation_id=row.id, cursor=cursor_to_json(progress.cursor) or {}
            )
        progress.pages += 1
        done, total = await refresh_progress(row.id)
        logger.info(
            "vector_index.build.progress",
            generation=row.generation,
            pages=progress.pages,
            documents_done=done,
            documents_total=total,
        )
    if progress.finished:
        await refresh_progress(row.id)
        progress.verify = await lifecycle_service.verify(generation=row.generation)
        logger.info(
            "vector_index.build.completed",
            generation=row.generation,
            documents_written=progress.documents_written,
            documents_skipped=progress.documents_skipped,
            verified=progress.verify.passed,
        )
    return progress


@dataclass(frozen=True)
class _DocumentRef:
    organization_id: UUID
    id: UUID
    uploaded_by_user_id: UUID
    filename: str
    file_type: str
    chunking_strategy: str | None
    chunking_profile_version: str | None

    @classmethod
    def from_row(cls, row: Any) -> _DocumentRef:
        return cls(
            organization_id=row.organization_id,
            id=row.id,
            uploaded_by_user_id=row.uploaded_by_user_id,
            filename=row.filename,
            file_type=row.file_type,
            chunking_strategy=row.chunking_strategy,
            chunking_profile_version=row.chunking_profile_version,
        )
