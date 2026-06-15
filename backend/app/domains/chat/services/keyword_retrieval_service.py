from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeywordRetrievedCandidate:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    section_path: str | None
    keyword_score: float
    # True when the query contained an exact-match token found in the chunk.
    exact_match_hit: bool = False
    # Parent-child context (F300): populated for child chunks (chunk_level=1).
    chunk_level: int = 0
    parent_chunk_id: UUID | None = None
    parent_text: str | None = None


@dataclass(frozen=True)
class KeywordRetrievalResult:
    candidates: list[KeywordRetrievedCandidate]
    query_tokens: list[str]
    exact_match_tokens: list[str]


# ---------------------------------------------------------------------------
# Exact-match token detection
# ---------------------------------------------------------------------------

_EXACT_MATCH_PATTERNS = [
    re.compile(r"\b[A-Z]{2,}(?:[_-][A-Z0-9]+)+\b"),   # POLICY-001, SOC-2
    re.compile(r"\b[A-Z]{2,10}-\d{1,6}\b"),             # JIRA-123, PROJ-9
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),               # 2024-01-15 dates
    re.compile(r"\b[A-Z]{3,8}\d{1,6}\b"),               # SOC2, ISO27001
    re.compile(r"\b[A-Z]{2,8}\b"),                       # acronyms: GDPR, HIPAA
]


def _extract_exact_match_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    for pattern in _EXACT_MATCH_PATTERNS:
        for match in pattern.finditer(query):
            token = match.group()
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    return tokens


def _has_exact_match(chunk_text: str, section_path: str | None, tokens: list[str]) -> bool:
    search_text = chunk_text + " " + (section_path or "")
    search_upper = search_text.upper()
    return any(token.upper() in search_upper for token in tokens)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class KeywordRetrievalService:
    """PostgreSQL full-text search (BM25-equivalent via ts_rank) for chunks."""

    async def search_chunks(
        self,
        *,
        session: AsyncSession,
        query: str,
        organization_id: UUID,
        document_ids: list[UUID] | None,
        top_k: int,
        exact_match_boost: float = 1.5,
    ) -> KeywordRetrievalResult:
        if not query.strip():
            return KeywordRetrievalResult(candidates=[], query_tokens=[], exact_match_tokens=[])
        if document_ids is not None and len(document_ids) == 0:
            return KeywordRetrievalResult(candidates=[], query_tokens=[], exact_match_tokens=[])

        exact_match_tokens = _extract_exact_match_tokens(query)

        tsquery = func.plainto_tsquery("english", query)
        rank_expr = func.ts_rank(DocumentChunk.text_search_vector, tsquery)

        # Left-join parent chunk at table level to avoid ORM mapper ambiguity (F300).
        _parent_alias = DocumentChunk.__table__.alias("parent_chunk")
        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.document_id,
                DocumentChunk.text,
                DocumentChunk.page_number,
                DocumentChunk.section_path,
                DocumentChunk.chunk_level,
                DocumentChunk.parent_chunk_id,
                _parent_alias.c.text.label("parent_text"),
                Document.filename,
                rank_expr.label("rank_score"),
            )
            .join(Document, DocumentChunk.document_id == Document.id)
            .outerjoin(_parent_alias, DocumentChunk.parent_chunk_id == _parent_alias.c.id)
            .where(
                Document.organization_id == organization_id,
                Document.status == "indexed",
                DocumentChunk.text_search_vector.op("@@")(tsquery),
            )
            .order_by(rank_expr.desc())
            .limit(top_k)
        )

        if document_ids is not None:
            stmt = stmt.where(DocumentChunk.document_id.in_(document_ids))

        rows = (await session.execute(stmt)).mappings().all()

        candidates: list[KeywordRetrievedCandidate] = []
        for row in rows:
            chunk_text = str(row["text"] or "")
            section_path = str(row["section_path"] or "") or None
            raw_score = float(row["rank_score"] or 0.0)
            exact_hit = bool(
                exact_match_tokens and _has_exact_match(chunk_text, section_path, exact_match_tokens)
            )
            score = raw_score * exact_match_boost if exact_hit else raw_score

            raw_page = row["page_number"]
            page_number = int(raw_page) if isinstance(raw_page, int) and raw_page >= 1 else None

            # Double-check org isolation on each row (defence-in-depth).
            try:
                doc_id = UUID(str(row["document_id"]))
            except (TypeError, ValueError):
                continue

            if document_ids is not None and doc_id not in document_ids:
                continue

            try:
                chunk_id = UUID(str(row["chunk_id"]))
            except (TypeError, ValueError):
                continue

            chunk_level = int(row["chunk_level"] or 0)
            raw_parent_id = row["parent_chunk_id"]
            parent_chunk_id: UUID | None = None
            if raw_parent_id:
                try:
                    parent_chunk_id = UUID(str(raw_parent_id))
                except (TypeError, ValueError):
                    pass
            raw_parent_text = row["parent_text"]
            parent_text = str(raw_parent_text).strip() if raw_parent_text else None

            candidates.append(
                KeywordRetrievedCandidate(
                    document_id=doc_id,
                    chunk_id=chunk_id,
                    filename=str(row["filename"] or ""),
                    page_number=page_number,
                    text=chunk_text,
                    section_path=section_path,
                    keyword_score=score,
                    exact_match_hit=exact_hit,
                    chunk_level=chunk_level,
                    parent_chunk_id=parent_chunk_id,
                    parent_text=parent_text,
                )
            )

        query_tokens = [t.strip() for t in query.split() if t.strip()]
        return KeywordRetrievalResult(
            candidates=candidates,
            query_tokens=query_tokens,
            exact_match_tokens=exact_match_tokens,
        )
