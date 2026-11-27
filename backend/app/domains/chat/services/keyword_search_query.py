"""SQL for keyword (full-text) chunk search (R03-01, R06-09).

One statement per search. A candidate subquery applies every filter (tenant, document
status, document ids, index versions, the text match) and stops after
``KEYWORD_SEARCH_CANDIDATE_LIMIT`` rows in index scan order, without sorting; only those
candidates are ranked with ``ts_rank`` and the best ``top_k`` returned. ``0`` removes the
bound (every match is ranked, the pre-0.6.0 behaviour). When more chunks match than the
bound, which ones are ranked depends on the scan order, not on relevance.

Tenant scoping:

- join path (default until the backfill is complete): ``documents.organization_id``;
- tenant column path: ``document_chunks.organization_id`` is filtered first (index
  ``idx_chunks_org_document``) and documents is joined only for status and filename.
  ``KEYWORD_SEARCH_TENANT_COLUMN=auto`` takes it once no chunk has a NULL
  ``organization_id``, checked once per process and cached.

Matching: with ``KEYWORD_SEARCH_MULTILINGUAL`` off, the generated English column
``text_search_vector`` and ``plainto_tsquery('english', q)``, as before. With it on,
``fts_vector @@ plainto_tsquery(<question config>, q)`` (index ``idx_chunks_fts_vector``);
a chunk not backfilled yet (``fts_vector`` NULL) still matches through the English column.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.chat.services.language_service import detect_language
from app.domains.documents.services.fts_config import fts_config_for_language
from app.models.document import Document, DocumentChunk

logger = get_logger("chat.keyword_search")

_tenant_column_ready: bool | None = None


@dataclass(frozen=True)
class KeywordSearchPlan:
    multilingual: bool
    tenant_column: bool
    candidate_limit: int
    question_config: str


def reset_tenant_column_cache() -> None:
    """Forget the cached backfill check (tests; operators restart workers instead)."""
    global _tenant_column_ready
    _tenant_column_ready = None


async def use_tenant_column(session: AsyncSession) -> bool:
    """Whether to scope by ``document_chunks.organization_id`` (``KEYWORD_SEARCH_TENANT_COLUMN``)."""
    global _tenant_column_ready
    mode = settings.keyword_search_tenant_column
    if mode == "on":
        return True
    if mode == "off":
        return False
    if _tenant_column_ready is None:
        has_null = select(DocumentChunk.id).where(DocumentChunk.organization_id.is_(None))
        pending = bool((await session.execute(select(has_null.exists()))).scalar())
        _tenant_column_ready = not pending
        logger.info("keyword_search.tenant_column_checked", ready=_tenant_column_ready)
    return _tenant_column_ready


def question_fts_config(query: str, query_language: str | None) -> str:
    """Text search configuration for the question; detected from the text when not given."""
    language = query_language or detect_language(query)
    return fts_config_for_language(language)


def _match_and_rank(plan: KeywordSearchPlan, query: str) -> tuple[Any, Any]:
    english = func.plainto_tsquery("english", query)
    english_match = DocumentChunk.text_search_vector.op("@@")(english)
    english_rank = func.ts_rank(DocumentChunk.text_search_vector, english)
    if not plan.multilingual:
        return english_match, english_rank
    question = func.plainto_tsquery(cast(plan.question_config, REGCONFIG), query)
    match = or_(
        DocumentChunk.fts_vector.op("@@")(question),
        and_(DocumentChunk.fts_vector.is_(None), english_match),
    )
    rank = case(
        (DocumentChunk.fts_vector.is_not(None), func.ts_rank(DocumentChunk.fts_vector, question)),
        else_=english_rank,
    )
    return match, rank


def build_keyword_search_statement(
    *,
    plan: KeywordSearchPlan,
    query: str,
    organization_id: UUID,
    document_ids: list[UUID] | None,
    top_k: int,
    index_version: str | None,
    index_versions: Sequence[str] | None,
) -> Select[Any]:
    match, rank = _match_and_rank(plan, query)
    tenant_filter = (
        DocumentChunk.organization_id == organization_id
        if plan.tenant_column
        else Document.organization_id == organization_id
    )
    candidates = (
        select(DocumentChunk.id.label("candidate_id"))
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(tenant_filter, Document.status == "indexed", match)
    )
    if document_ids is not None:
        candidates = candidates.where(DocumentChunk.document_id.in_(document_ids))
    if index_version is not None:
        candidates = candidates.where(DocumentChunk.index_version == index_version)
    if index_versions is not None:
        candidates = candidates.where(DocumentChunk.index_version.in_(list(index_versions)))
    if plan.candidate_limit > 0:
        candidates = candidates.limit(plan.candidate_limit)
    candidate_ids = candidates.subquery("keyword_candidates")

    # Left-join parent chunk at table level to avoid ORM mapper ambiguity (F300).
    parent = DocumentChunk.__table__.alias("parent_chunk")
    return (
        select(
            DocumentChunk.id.label("chunk_id"),
            DocumentChunk.document_id,
            DocumentChunk.text,
            DocumentChunk.page_number,
            DocumentChunk.section_path,
            DocumentChunk.chunk_level,
            DocumentChunk.parent_chunk_id,
            DocumentChunk.organization_id.label("chunk_organization_id"),
            parent.c.text.label("parent_text"),
            Document.filename,
            Document.organization_id.label("document_organization_id"),
            rank.label("rank_score"),
        )
        .select_from(candidate_ids)
        .join(DocumentChunk, DocumentChunk.id == candidate_ids.c.candidate_id)
        .join(Document, DocumentChunk.document_id == Document.id)
        .outerjoin(parent, DocumentChunk.parent_chunk_id == parent.c.id)
        .order_by(rank.desc(), DocumentChunk.id)
        .limit(top_k)
    )


def row_belongs_to(row: Mapping[str, Any], organization_id: UUID) -> bool:
    """Per-row isolation check: the document's and (when set) the chunk's tenant match."""
    if str(row.get("document_organization_id")) != str(organization_id):
        return False
    chunk_org = row.get("chunk_organization_id")
    return chunk_org is None or str(chunk_org) == str(organization_id)
