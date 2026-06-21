"""Document version service (F253).

Handles creation and retrieval of DocumentVersion records. A version is created
on initial upload, content re-upload, connector sync with changed content, and
explicit reindex. Each version is an immutable snapshot; only is_current changes
after creation (when a later version becomes the active one).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_version import DocumentVersion
from app.models.enums import DocumentVersionChangeReason

if TYPE_CHECKING:
    from app.models.document import Document


async def _next_version_number(
    db_session: AsyncSession,
    *,
    document_id: UUID,
) -> int:
    result = await db_session.execute(
        select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document_id
        )
    )
    current_max = result.scalar_one_or_none()
    return (current_max or 0) + 1


async def create_document_version(
    db_session: AsyncSession,
    *,
    document: "Document",
    change_reason: DocumentVersionChangeReason,
    content_hash: str | None = None,
    created_by_user_id: UUID | None = None,
    source_updated_at: datetime | None = None,
    chunking_profile_id: UUID | None = None,
    chunking_profile_snapshot: dict | None = None,
) -> DocumentVersion:
    """Create a new version snapshot for document and mark it as current.

    Clears is_current from any previously current version first (within the same
    flush so the unique-index invariant is never violated between statements).
    Does not commit — callers own the transaction boundary.
    """
    version_number = await _next_version_number(db_session, document_id=document.id)

    # Clear current flag on previous version.
    if version_number > 1:
        prev_result = await db_session.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.is_current.is_(True),
            )
        )
        for prev in prev_result.scalars():
            prev.is_current = False

    version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        organization_id=document.organization_id,
        version_number=version_number,
        change_reason=change_reason.value,
        content_hash=content_hash or document.checksum,
        filename=document.filename,
        page_count=document.page_count,
        chunk_count=document.chunk_count,
        status=document.status,
        is_current=True,
        source_updated_at=source_updated_at,
        created_by_user_id=created_by_user_id,
        chunking_profile_id=chunking_profile_id,
        chunking_profile_snapshot=chunking_profile_snapshot or document.chunking_config_snapshot,
        embedding_model=document.embedding_provider_type,
        embedding_vector_dimension=document.embedding_vector_dimension,
        index_version=None,
    )
    db_session.add(version)
    await db_session.flush()

    # Point document at new current version.
    document.current_version_id = version.id
    await db_session.flush()

    return version


async def mark_version_indexed(
    db_session: AsyncSession,
    *,
    version: DocumentVersion,
    document: "Document",
    chunk_count: int | None = None,
    embedding_model: str | None = None,
    embedding_vector_dimension: int | None = None,
    index_version: str | None = None,
    extraction_hash: str | None = None,
) -> None:
    """Update an existing version with post-indexing provenance fields.

    Called after the indexing pipeline completes so the snapshot captures the
    actual embedding model and index_version used (which may differ from defaults
    if provider routing or fallback occurred during this run).
    """
    version.indexed_at = datetime.now(UTC)
    if chunk_count is not None:
        version.chunk_count = chunk_count
    if embedding_model is not None:
        version.embedding_model = embedding_model
    if embedding_vector_dimension is not None:
        version.embedding_vector_dimension = embedding_vector_dimension
    if index_version is not None:
        version.index_version = index_version
    if extraction_hash is not None:
        version.extraction_hash = extraction_hash
    version.status = document.status
    await db_session.flush()


async def get_document_versions(
    db_session: AsyncSession,
    *,
    document_id: UUID,
    organization_id: UUID,
) -> list[DocumentVersion]:
    """Return all versions for document_id, newest first, scoped to organization."""
    result = await db_session.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.organization_id == organization_id,
        )
        .order_by(DocumentVersion.version_number.desc())
    )
    return list(result.scalars().all())
