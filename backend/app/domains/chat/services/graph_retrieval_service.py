from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.graph.services.entity_resolution_service import normalize_entity_name
from app.domains.graph.services.graph_service import GraphService
from app.models.document import Document, DocumentChunk

logger = get_logger("chat.graph_retrieval")

_QUOTED_ENTITY_RE = re.compile(r"[\"“”']([^\"“”']{2,80})[\"“”']")
_TITLE_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][\w&.-]*|[A-Z0-9]{2,})(?:\s+(?:[A-Z][\w&.-]*|[A-Z0-9]{2,})){0,4}\b"
)
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,10}\b")
_QUESTION_STOPWORDS = {
    "how",
    "what",
    "when",
    "where",
    "why",
    "who",
    "whom",
    "which",
    "whose",
    "tell",
    "show",
    "list",
    "explain",
    "please",
    "does",
    "do",
    "did",
    "is",
    "are",
    "was",
    "were",
    "can",
    "could",
    "would",
    "should",
    "may",
    "might",
    "will",
    "have",
    "has",
    "had",
}


@dataclass(frozen=True)
class GraphRetrievedChunk:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    graph_score: float
    graph_source_entity_ids: tuple[UUID, ...] = ()
    graph_source_entity_names: tuple[str, ...] = ()
    graph_hops: int = 0
    graph_confidence: float | None = None


@dataclass(frozen=True)
class GraphRetrievalResult:
    chunks: list[GraphRetrievedChunk] = field(default_factory=list)
    graph_context_enabled: bool = False
    graph_context_used: bool = False
    graph_context_unavailable: bool = False
    graph_context_reason: str | None = None
    graph_seed_entity_count: int = 0
    graph_related_entity_count: int = 0
    graph_chunk_count: int = 0
    graph_max_hops_used: int = 0
    graph_relation_types_used: tuple[str, ...] = ()


@dataclass(frozen=True)
class _GraphEntityHit:
    entity_id: UUID
    canonical_name: str
    entity_type: str | None
    hops: int


@dataclass(frozen=True)
class _GraphChunkCandidate:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int | None
    text: str
    graph_score: float
    graph_confidence: float | None
    graph_source_entity_ids: tuple[UUID, ...]
    graph_source_entity_names: tuple[str, ...]
    graph_hops: int


class GraphRetrievalService:
    def __init__(self, graph_service: GraphService | None = None) -> None:
        self._graph_service = graph_service or GraphService()

    @staticmethod
    def _extract_entity_candidates(question: str) -> list[str]:
        raw_candidates: list[str] = []
        for match in _QUOTED_ENTITY_RE.findall(question):
            candidate = match.strip()
            if candidate:
                raw_candidates.append(candidate)

        for match in _TITLE_ENTITY_RE.findall(question):
            candidate = match.strip()
            if candidate:
                raw_candidates.append(candidate)

        for match in _ACRONYM_RE.findall(question):
            candidate = match.strip()
            if candidate:
                raw_candidates.append(candidate)

        normalized_candidates: list[str] = []
        seen: set[str] = set()
        for candidate in raw_candidates:
            normalized = normalize_entity_name(candidate)
            if not normalized or normalized in seen:
                continue
            tokens = normalized.split()
            if not tokens:
                continue
            if all(token in _QUESTION_STOPWORDS for token in tokens):
                continue
            seen.add(normalized)
            normalized_candidates.append(candidate)
        return normalized_candidates

    @staticmethod
    def _graph_score(*, confidence: float, hops: int) -> float:
        safe_confidence = max(0.0, min(1.0, confidence))
        safe_hops = max(0, hops)
        hop_penalty = 1.0 if safe_hops == 0 else max(0.45, 1.0 - (0.15 * safe_hops))
        return round(max(0.0, min(1.0, safe_confidence * hop_penalty)), 4)

    async def expand(
        self,
        *,
        session: AsyncSession,
        organization_id: UUID,
        question: str,
        allowed_document_ids: list[UUID] | None,
        graph_enabled: bool,
    ) -> GraphRetrievalResult:
        if not graph_enabled:
            return GraphRetrievalResult(
                graph_context_enabled=False,
                graph_context_used=False,
                graph_context_reason="disabled",
            )

        if not question.strip():
            return GraphRetrievalResult(
                graph_context_enabled=True,
                graph_context_used=False,
                graph_context_reason="empty_question",
            )

        if not self._graph_service.is_available():
            return GraphRetrievalResult(
                graph_context_enabled=True,
                graph_context_used=False,
                graph_context_unavailable=True,
                graph_context_reason="neo4j_unavailable",
            )

        candidates = self._extract_entity_candidates(question)
        if not candidates:
            return GraphRetrievalResult(
                graph_context_enabled=True,
                graph_context_used=False,
                graph_context_reason="no_entities_detected",
            )

        seed_hits: list[_GraphEntityHit] = []
        seen_entity_ids: set[UUID] = set()
        for candidate in candidates:
            matches = await self._graph_service.find_entities_by_name(
                organization_id=organization_id,
                name_query=candidate,
                limit=3,
            )
            for match in matches:
                raw_entity_id = match.get("entity_id")
                raw_canonical_name = match.get("canonical_name")
                if raw_entity_id is None or raw_canonical_name is None:
                    continue
                try:
                    entity_id = UUID(str(raw_entity_id))
                except ValueError:
                    continue
                if entity_id in seen_entity_ids:
                    continue
                seen_entity_ids.add(entity_id)
                seed_hits.append(
                    _GraphEntityHit(
                        entity_id=entity_id,
                        canonical_name=str(raw_canonical_name),
                        entity_type=str(match.get("entity_type") or "").strip() or None,
                        hops=0,
                    )
                )

        if not seed_hits:
            return GraphRetrievalResult(
                graph_context_enabled=True,
                graph_context_used=False,
                graph_context_reason="no_matching_entities",
            )

        related_hits: list[_GraphEntityHit] = []
        related_seen: set[UUID] = set()
        related_rows = await self._graph_service.find_related_entities(
            organization_id=organization_id,
            entity_ids=[hit.entity_id for hit in seed_hits],
            depth=settings.graph_rag_max_hops,
            limit=settings.graph_rag_max_related_entities,
            relationship_types=settings.graph_rag_relation_type_allowlist,
        )
        for row in related_rows:
            raw_entity_id = row.get("entity_id")
            raw_canonical_name = row.get("canonical_name")
            if raw_entity_id is None or raw_canonical_name is None:
                continue
            try:
                entity_id = UUID(str(raw_entity_id))
            except ValueError:
                continue
            if entity_id in seen_entity_ids or entity_id in related_seen:
                continue
            hops = int(row.get("hops") or settings.graph_rag_max_hops)
            related_seen.add(entity_id)
            related_hits.append(
                _GraphEntityHit(
                    entity_id=entity_id,
                    canonical_name=str(raw_canonical_name),
                    entity_type=str(row.get("entity_type") or "").strip() or None,
                    hops=max(1, hops),
                )
            )

        entity_hops: dict[UUID, int] = {hit.entity_id: hit.hops for hit in seed_hits}
        entity_names: dict[UUID, str] = {
            hit.entity_id: hit.canonical_name for hit in (*seed_hits, *related_hits)
        }
        for hit in related_hits:
            entity_hops[hit.entity_id] = min(entity_hops.get(hit.entity_id, hit.hops), hit.hops)

        all_entity_ids = [*entity_hops.keys()]
        evidence_rows = await self._graph_service.get_evidence_for_entities(
            organization_id=organization_id,
            entity_ids=all_entity_ids,
            limit=max(settings.graph_rag_max_chunks * 3, settings.graph_rag_max_chunks),
            document_ids=allowed_document_ids,
            confidence_threshold=settings.graph_rag_confidence_threshold,
        )
        if not evidence_rows:
            return GraphRetrievalResult(
                graph_context_enabled=True,
                graph_context_used=False,
                graph_context_reason="no_graph_chunks",
                graph_seed_entity_count=len(seed_hits),
                graph_related_entity_count=len(related_hits),
                graph_max_hops_used=max((hit.hops for hit in related_hits), default=0),
                graph_relation_types_used=tuple(settings.graph_rag_relation_type_allowlist),
            )

        candidate_map: dict[UUID, _GraphChunkCandidate] = {}
        allowed_document_ids_set = (
            {document_id for document_id in allowed_document_ids}
            if allowed_document_ids is not None
            else None
        )

        def _merge_unique_ids(*tuples: tuple[UUID, ...]) -> tuple[UUID, ...]:
            merged: list[UUID] = []
            seen: set[UUID] = set()
            for tuple_values in tuples:
                for item in tuple_values:
                    if item in seen:
                        continue
                    seen.add(item)
                    merged.append(item)
            return tuple(merged)

        def _merge_unique_names(*tuples: tuple[str, ...]) -> tuple[str, ...]:
            merged: list[str] = []
            seen: set[str] = set()
            for tuple_values in tuples:
                for item in tuple_values:
                    if item in seen:
                        continue
                    seen.add(item)
                    merged.append(item)
            return tuple(merged)

        for row in evidence_rows:
            raw_entity_id = row.get("entity_id")
            raw_chunk_id = row.get("chunk_id")
            raw_document_id = row.get("source_document_id")
            raw_confidence = row.get("confidence")
            raw_citation_text = row.get("citation_text")
            raw_evidence_text = row.get("evidence_text")
            raw_page_number = row.get("page_number")
            if raw_entity_id is None or raw_chunk_id is None or raw_document_id is None:
                continue
            try:
                entity_id = UUID(str(raw_entity_id))
                chunk_id = UUID(str(raw_chunk_id))
                document_id = UUID(str(raw_document_id))
            except ValueError:
                continue
            if allowed_document_ids_set is not None and document_id not in allowed_document_ids_set:
                continue

            confidence = float(raw_confidence or 0.0)
            hops = entity_hops.get(entity_id, settings.graph_rag_max_hops)
            score = self._graph_score(confidence=confidence, hops=hops)
            if score < settings.graph_rag_confidence_threshold:
                continue

            source_entity_name = entity_names.get(entity_id, str(raw_entity_id))
            source_entity_ids = (entity_id,)
            source_entity_names = (source_entity_name,)
            text = str(raw_citation_text or raw_evidence_text or "").strip()
            if not text:
                continue
            page_number = (
                raw_page_number
                if isinstance(raw_page_number, int) and raw_page_number > 0
                else None
            )

            existing = candidate_map.get(chunk_id)
            if existing is None:
                candidate_map[chunk_id] = _GraphChunkCandidate(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    filename="",
                    page_number=page_number,
                    text=text,
                    graph_score=score,
                    graph_confidence=confidence,
                    graph_source_entity_ids=source_entity_ids,
                    graph_source_entity_names=source_entity_names,
                    graph_hops=hops,
                )
                continue

            if score > existing.graph_score:
                candidate_map[chunk_id] = _GraphChunkCandidate(
                    chunk_id=existing.chunk_id,
                    document_id=document_id,
                    filename=existing.filename,
                    page_number=existing.page_number or page_number,
                    text=text,
                    graph_score=score,
                    graph_confidence=max(existing.graph_confidence or 0.0, confidence),
                    graph_source_entity_ids=_merge_unique_ids(
                        existing.graph_source_entity_ids,
                        source_entity_ids,
                    ),
                    graph_source_entity_names=_merge_unique_names(
                        existing.graph_source_entity_names,
                        source_entity_names,
                    ),
                    graph_hops=min(existing.graph_hops, hops),
                )
                continue

            candidate_map[chunk_id] = _GraphChunkCandidate(
                chunk_id=existing.chunk_id,
                document_id=existing.document_id,
                filename=existing.filename,
                page_number=existing.page_number or page_number,
                text=existing.text,
                graph_score=max(existing.graph_score, score),
                graph_confidence=max(existing.graph_confidence or 0.0, confidence),
                graph_source_entity_ids=_merge_unique_ids(
                    existing.graph_source_entity_ids,
                    source_entity_ids,
                ),
                graph_source_entity_names=_merge_unique_names(
                    existing.graph_source_entity_names,
                    source_entity_names,
                ),
                graph_hops=min(existing.graph_hops, hops),
            )

        if not candidate_map:
            return GraphRetrievalResult(
                graph_context_enabled=True,
                graph_context_used=False,
                graph_context_reason="no_graph_chunks",
                graph_seed_entity_count=len(seed_hits),
                graph_related_entity_count=len(related_hits),
                graph_max_hops_used=max((hit.hops for hit in related_hits), default=0),
                graph_relation_types_used=tuple(settings.graph_rag_relation_type_allowlist),
            )

        chunk_rows = await self._load_chunk_rows(
            session,
            organization_id=organization_id,
            chunk_ids=list(candidate_map.keys()),
            allowed_document_ids=allowed_document_ids,
        )
        if not chunk_rows:
            return GraphRetrievalResult(
                graph_context_enabled=True,
                graph_context_used=False,
                graph_context_reason="no_graph_chunks",
                graph_seed_entity_count=len(seed_hits),
                graph_related_entity_count=len(related_hits),
                graph_max_hops_used=max((hit.hops for hit in related_hits), default=0),
                graph_relation_types_used=tuple(settings.graph_rag_relation_type_allowlist),
            )

        chunk_lookup = {chunk_id: candidate_map[chunk_id] for chunk_id in candidate_map}
        graph_chunks: list[GraphRetrievedChunk] = []
        for chunk_row, filename in chunk_rows:
            candidate = chunk_lookup.get(chunk_row.id)
            if candidate is None:
                continue
            text = str(chunk_row.text or "").strip()
            if not text:
                continue
            graph_chunks.append(
                GraphRetrievedChunk(
                    document_id=chunk_row.document_id,
                    chunk_id=chunk_row.id,
                    filename=filename,
                    page_number=chunk_row.page_number,
                    text=text,
                    similarity_score=candidate.graph_score,
                    graph_score=candidate.graph_score,
                    graph_source_entity_ids=candidate.graph_source_entity_ids,
                    graph_source_entity_names=candidate.graph_source_entity_names,
                    graph_hops=candidate.graph_hops,
                    graph_confidence=candidate.graph_confidence,
                )
            )

        graph_chunks.sort(
            key=lambda chunk: (
                chunk.graph_score,
                chunk.similarity_score,
                chunk.filename,
                str(chunk.chunk_id),
            ),
            reverse=True,
        )
        graph_chunks = graph_chunks[: settings.graph_rag_max_chunks]
        if not graph_chunks:
            return GraphRetrievalResult(
                graph_context_enabled=True,
                graph_context_used=False,
                graph_context_reason="no_graph_chunks",
                graph_seed_entity_count=len(seed_hits),
                graph_related_entity_count=len(related_hits),
                graph_max_hops_used=max((hit.hops for hit in related_hits), default=0),
                graph_relation_types_used=tuple(settings.graph_rag_relation_type_allowlist),
            )

        return GraphRetrievalResult(
            chunks=graph_chunks,
            graph_context_enabled=True,
            graph_context_used=True,
            graph_seed_entity_count=len(seed_hits),
            graph_related_entity_count=len(related_hits),
            graph_chunk_count=len(graph_chunks),
            graph_max_hops_used=max((hit.hops for hit in related_hits), default=0),
            graph_relation_types_used=tuple(settings.graph_rag_relation_type_allowlist),
        )

    async def _load_chunk_rows(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        chunk_ids: list[UUID],
        allowed_document_ids: list[UUID] | None,
    ) -> list[tuple[DocumentChunk, str]]:
        if not chunk_ids:
            return []

        statement = (
            select(DocumentChunk, Document.filename)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                Document.organization_id == organization_id,
                DocumentChunk.id.in_(chunk_ids),
            )
        )
        if allowed_document_ids is not None:
            statement = statement.where(DocumentChunk.document_id.in_(allowed_document_ids))

        result = await session.execute(
            statement.order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
        )
        rows: list[tuple[DocumentChunk, str]] = []
        for chunk_row, filename in result.all():
            rows.append((chunk_row, str(filename)))
        return rows
