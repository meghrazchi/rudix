"""Organisation-scoped status of the vector index generations (R06-08 admin read API).

Progress counts filter on the caller's ``organization_id`` in SQL (documents and
``vector_index_generation_documents``), so another organisation's numbers are never
read, let alone returned. Cross-tenant progress exists only as the
``rudix_reindex_progress`` metric.
"""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.vector_index.repositories import generations as repo
from app.domains.vector_index.schemas.vector_index import (
    VectorIndexActiveGeneration,
    VectorIndexBuildingGeneration,
    VectorIndexOrganizationProgress,
    VectorIndexStatusResponse,
)
from app.domains.vector_index.services.generation_service import configured_alias


async def organization_status(
    session: AsyncSession, *, organization_id: UUID
) -> VectorIndexStatusResponse:
    alias = configured_alias()
    if alias is None:
        return VectorIndexStatusResponse(
            alias=None,
            legacy_mode=True,
            active=VectorIndexActiveGeneration(
                generation=None,
                embedding_model=settings.openai_embedding_model.strip(),
                vector_size=settings.qdrant_vector_size,
            ),
        )
    rows = await repo.list_generations(session, alias_name=alias)
    active_row = repo.pick(rows, ("active",))
    building_row = repo.pick(rows, repo.BUILDING_STATES)
    active = (
        VectorIndexActiveGeneration(
            generation=active_row.generation,
            embedding_model=active_row.embedding_model,
            vector_size=active_row.vector_size,
            activated_at=active_row.activated_at,
        )
        if active_row is not None
        else None
    )
    if building_row is None:
        return VectorIndexStatusResponse(alias=alias, legacy_mode=False, active=active)
    total = await repo.count_indexed_documents(session, organization_id=organization_id)
    done, _ = await repo.generation_progress(
        session, generation_id=building_row.id, organization_id=organization_id
    )
    return VectorIndexStatusResponse(
        alias=alias,
        legacy_mode=False,
        active=active,
        building=VectorIndexBuildingGeneration(
            generation=building_row.generation,
            embedding_model=building_row.embedding_model,
            state=cast(Literal["building", "verifying"], building_row.state),
            started_at=building_row.created_at,
        ),
        progress=VectorIndexOrganizationProgress(
            documents_total=total, documents_done=min(done, total)
        ),
    )
