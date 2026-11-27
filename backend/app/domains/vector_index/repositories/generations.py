"""Persistence of vector index generations (R06-08).

``vector_index_generations`` is global (one row per Qdrant collection behind the alias);
``vector_index_generation_documents`` is per organisation under strict row-level security,
so its writes run in a session bound to the document's tenant and its cross-tenant reads
(build progress, metrics) in ``maintenance_session()``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus
from app.models.vector_index import VectorIndexGeneration, VectorIndexGenerationDocument

LIVE_STATES = ("building", "verifying", "active", "retired", "failed")
BUILDING_STATES = ("building", "verifying")


async def list_generations(
    session: AsyncSession, *, alias_name: str
) -> list[VectorIndexGeneration]:
    rows = await session.execute(
        select(VectorIndexGeneration)
        .where(VectorIndexGeneration.alias_name == alias_name)
        .order_by(VectorIndexGeneration.generation)
    )
    return list(rows.scalars())


async def get_generation(
    session: AsyncSession, *, alias_name: str, generation: int
) -> VectorIndexGeneration | None:
    row = await session.execute(
        select(VectorIndexGeneration).where(
            VectorIndexGeneration.alias_name == alias_name,
            VectorIndexGeneration.generation == generation,
        )
    )
    return row.scalar_one_or_none()


async def get_by_id(session: AsyncSession, generation_id: UUID) -> VectorIndexGeneration | None:
    return await session.get(VectorIndexGeneration, generation_id)


def pick(
    generations: Sequence[VectorIndexGeneration], states: Sequence[str]
) -> VectorIndexGeneration | None:
    """The newest generation in one of ``states``."""
    matching = [g for g in generations if g.state in states]
    return max(matching, key=lambda g: g.generation) if matching else None


async def create_generation(
    session: AsyncSession,
    *,
    alias_name: str,
    collection_name: str,
    embedding_model: str,
    vector_size: int,
    distance: str,
    generation: int,
    state: str,
    activated_at: datetime | None = None,
) -> VectorIndexGeneration:
    row = VectorIndexGeneration(
        alias_name=alias_name,
        collection_name=collection_name,
        embedding_model=embedding_model,
        vector_size=vector_size,
        distance=distance,
        generation=generation,
        state=state,
        activated_at=activated_at,
        documents_done=0,
        indexed_points=0,
    )
    session.add(row)
    await session.flush()
    return row


async def set_build_cursor(
    session: AsyncSession, *, generation_id: UUID, cursor: dict[str, Any]
) -> None:
    await session.execute(
        update(VectorIndexGeneration)
        .where(VectorIndexGeneration.id == generation_id)
        .values(build_cursor=cursor)
    )


async def record_generation_document(
    session: AsyncSession,
    *,
    generation_id: UUID,
    organization_id: UUID,
    document_id: UUID,
    point_count: int,
) -> None:
    """Insert or update the generation's row for the document (idempotent)."""
    existing = (
        await session.execute(
            select(VectorIndexGenerationDocument).where(
                VectorIndexGenerationDocument.generation_id == generation_id,
                VectorIndexGenerationDocument.document_id == document_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            VectorIndexGenerationDocument(
                generation_id=generation_id,
                organization_id=organization_id,
                document_id=document_id,
                point_count=point_count,
            )
        )
    else:
        existing.point_count = point_count
        existing.indexed_at = func.now()
    await session.flush()


async def generation_has_document(
    session: AsyncSession, *, generation_id: UUID, document_id: UUID
) -> bool:
    found = await session.execute(
        select(VectorIndexGenerationDocument.id).where(
            VectorIndexGenerationDocument.generation_id == generation_id,
            VectorIndexGenerationDocument.document_id == document_id,
        )
    )
    return found.first() is not None


async def count_indexed_documents(
    session: AsyncSession, *, organization_id: UUID | None = None
) -> int:
    statement = select(func.count(Document.id)).where(
        Document.status == DocumentStatus.indexed.value
    )
    if organization_id is not None:
        statement = statement.where(Document.organization_id == organization_id)
    return int((await session.execute(statement)).scalar_one() or 0)


async def generation_progress(
    session: AsyncSession, *, generation_id: UUID, organization_id: UUID | None = None
) -> tuple[int, int]:
    """(documents done, points) of indexed documents the generation holds."""
    statement = (
        select(
            func.count(VectorIndexGenerationDocument.id),
            func.coalesce(func.sum(VectorIndexGenerationDocument.point_count), 0),
        )
        .join(Document, Document.id == VectorIndexGenerationDocument.document_id)
        .where(
            VectorIndexGenerationDocument.generation_id == generation_id,
            Document.status == DocumentStatus.indexed.value,
        )
    )
    if organization_id is not None:
        statement = statement.where(
            VectorIndexGenerationDocument.organization_id == organization_id,
            Document.organization_id == organization_id,
        )
    done, points = (await session.execute(statement)).one()
    return int(done or 0), int(points or 0)


async def expected_points(session: AsyncSession, *, index_versions: Sequence[str]) -> int:
    """Embeddable chunk rows of indexed documents in the active index versions."""
    statement = (
        select(func.count(DocumentChunk.id))
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            Document.status == DocumentStatus.indexed.value,
            DocumentChunk.index_version.in_(list(index_versions)),
            DocumentChunk.qdrant_point_id.is_not(None),
        )
    )
    return int((await session.execute(statement)).scalar_one() or 0)


async def documents_page(
    session: AsyncSession, *, after: tuple[UUID, UUID] | None, limit: int
) -> list[Any]:
    """Next indexed documents by (organization_id, id) after the cursor."""
    statement = select(
        Document.organization_id,
        Document.id,
        Document.uploaded_by_user_id,
        Document.filename,
        Document.file_type,
        Document.chunking_strategy,
        Document.chunking_profile_version,
    ).where(Document.status == DocumentStatus.indexed.value)
    if after is not None:
        org, doc = after
        statement = statement.where(
            (Document.organization_id > org)
            | ((Document.organization_id == org) & (Document.id > doc))
        )
    statement = statement.order_by(Document.organization_id, Document.id).limit(limit)
    return list((await session.execute(statement)).all())
