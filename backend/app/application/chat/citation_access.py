"""Citation-level authorization shared by the HTTP and WebSocket chat transports.

Retrieved chunks whose document the principal may not ``cite`` are removed
before prompt assembly, so they can never surface as citations. Owners and
admins bypass the per-document check (policy-engine rule 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization_service import AuthorizationService
from app.auth.models import AuthenticatedPrincipal
from app.auth.policy_engine import Action
from app.auth.resource_context_builder import (
    build_document_resource_contexts_batch,
    get_subject_accessible_collection_ids,
)
from app.core.logging import log_query_event
from app.domains.documents.repositories.documents import DocumentRepository

_BYPASS_ROLES = frozenset({"owner", "admin"})

_authorization_service = AuthorizationService()
_document_repository = DocumentRepository()


class ChunkWithDocument(Protocol):
    @property
    def document_id(self) -> UUID | str: ...


def _as_uuid(value: UUID | str) -> UUID | None:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def filter_chunks_by_cite_access[ChunkT: ChunkWithDocument](
    db_session: AsyncSession,
    *,
    principal: AuthenticatedPrincipal,
    organization_id: UUID,
    user_id: UUID,
    user_roles: Sequence[str],
    chunks: Sequence[ChunkT],
) -> list[ChunkT]:
    """Return the chunks the principal may cite, preserving their order.

    Fails closed: chunks whose document is not found in the organisation, or
    whose document id is malformed, are dropped.
    """
    if not chunks:
        return []
    if _BYPASS_ROLES.intersection(user_roles):
        return list(chunks)

    unique_ids: list[UUID] = []
    seen: set[UUID] = set()
    for chunk in chunks:
        doc_uuid = _as_uuid(chunk.document_id)
        if doc_uuid is not None and doc_uuid not in seen:
            seen.add(doc_uuid)
            unique_ids.append(doc_uuid)

    documents = await _document_repository.get_documents_by_ids(
        db_session, document_ids=unique_ids, organization_id=organization_id
    )
    allowed_ids: set[str] = set()
    if documents:
        collection_ids = await get_subject_accessible_collection_ids(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            user_roles=list(user_roles),
        )
        contexts = await build_document_resource_contexts_batch(
            db_session,
            documents=documents,
            organization_id=organization_id,
            subject_accessible_collection_ids=collection_ids,
        )
        allowed = await _authorization_service.filter_accessible_resources(
            principal, Action.cite, contexts, db_session
        )
        allowed_ids = {ctx.resource_id for ctx in allowed if ctx.resource_id is not None}

    kept: list[ChunkT] = []
    for chunk in chunks:
        doc_uuid = _as_uuid(chunk.document_id)
        if doc_uuid is not None and str(doc_uuid) in allowed_ids:
            kept.append(chunk)

    dropped = len(chunks) - len(kept)
    if dropped:
        log_query_event(
            event="query.cite_filter.dropped_chunks",
            organization_id=str(organization_id),
            user_id=str(user_id),
            dropped_chunk_count=dropped,
            kept_chunk_count=len(kept),
            document_count=len(unique_ids),
        )
    return kept
