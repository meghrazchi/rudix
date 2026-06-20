from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.errors import AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.core.document_errors import decode_document_error
from app.db.session import SessionLocal
from app.domains.agents.schemas import ToolCall
from app.domains.agents.services.tool_registry import ToolRegistry
from app.domains.ai.profile.schemas import TaskType
from app.domains.ai.profile.service import resolve_task_profile
from app.domains.chat.services.citation_service import CitationContextChunk, CitationService
from app.domains.chat.services.confidence_service import (
    ConfidenceChunkSignal,
    ConfidenceService,
)
from app.domains.chat.services.llm_service import (
    LLMService,
    PermanentLLMServiceError,
    TransientLLMServiceError,
)
from app.domains.chat.services.prompt_service import PromptContextChunk, PromptService
from app.domains.chat.services.query_retrieval_service import (
    QueryRetrievalService,
    RetrievedCandidate,
)
from app.domains.chat.services.rerank_service import RerankCandidate, RerankService
from app.domains.documents.repositories.documents import DocumentRepository
from app.models.document import Document
from app.models.enums import DocumentStatus

_NOT_FOUND_RESPONSE = "I could not find this information in the accessible document context."


@dataclass(frozen=True)
class _RetrievedChunk:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    rerank_score: float | None = None
    rerank_rank: int | None = None


def _chunk_preview_text(text: str, *, max_length: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1].rstrip()}…"


def _safe_document_error(document: Document) -> tuple[str | None, object | None]:
    error_message, error_details = decode_document_error(document.error_message)
    if document.error_message is None:
        return None, None
    if error_details is not None:
        return error_message, error_details
    return "Processing failed", None


def _ensure_iso(value: Any) -> str | None:
    if value is None:
        return None
    isoformat_method = getattr(value, "isoformat", None)
    if callable(isoformat_method):
        return str(isoformat_method())
    return str(value)


def _category_from_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= settings.confidence_high_threshold:
        return "high"
    if score >= settings.confidence_medium_threshold:
        return "medium"
    return "low"


def _to_retrieved_chunk(candidate: RetrievedCandidate) -> _RetrievedChunk:
    return _RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
    )


def _coerce_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _coerce_optional_string(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    return normalized or None


def _coerce_int(
    value: object,
    *,
    field_name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        parsed = default
    elif isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    elif isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer") from exc
    else:
        raise ValueError(f"{field_name} must be an integer")
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _coerce_bool(value: object, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{field_name} must be a boolean")


class DocumentIntelligenceToolService:
    """Read-only document intelligence handlers shared by agent runtime and MCP adapters."""

    def __init__(
        self,
        *,
        document_repository: DocumentRepository | None = None,
        query_retrieval_service: QueryRetrievalService | None = None,
        rerank_service: RerankService | None = None,
        prompt_service: PromptService | None = None,
        citation_service: CitationService | None = None,
        confidence_service: ConfidenceService | None = None,
        llm_service: LLMService | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        qdrant_client: Any | None = None,
    ) -> None:
        self._document_repository = document_repository or DocumentRepository()
        self._query_retrieval_service = query_retrieval_service or QueryRetrievalService(
            qdrant_client=qdrant_client,
        )
        self._rerank_service = rerank_service or RerankService()
        self._prompt_service = prompt_service or PromptService()
        self._citation_service = citation_service or CitationService()
        self._confidence_service = confidence_service or ConfidenceService()
        self._llm_service = llm_service or LLMService()
        self._session_factory = session_factory or SessionLocal
        self._qdrant_client = qdrant_client

    async def search_documents(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        organization_id = self._organization_uuid(principal)
        arguments = call.arguments
        query = _coerce_optional_string(arguments.get("query"), field_name="query")
        status_filter = _coerce_optional_string(arguments.get("status"), field_name="status")
        if status_filter is not None and status_filter not in {
            status.value for status in DocumentStatus
        }:
            raise ValueError(
                "status must be one of uploaded|processing|indexed|failed|deleting|deleted"
            )
        sort_by = (
            _coerce_optional_string(arguments.get("sort_by"), field_name="sort_by") or "updated_at"
        )
        if sort_by not in {"created_at", "updated_at", "filename", "status"}:
            raise ValueError("sort_by must be one of created_at|updated_at|filename|status")
        sort_order = (
            _coerce_optional_string(arguments.get("sort_order"), field_name="sort_order") or "desc"
        )
        if sort_order not in {"asc", "desc"}:
            raise ValueError("sort_order must be one of asc|desc")
        limit = _coerce_int(
            arguments.get("limit"), field_name="limit", default=20, minimum=1, maximum=200
        )
        offset = _coerce_int(
            arguments.get("offset"), field_name="offset", default=0, minimum=0, maximum=100000
        )

        async with self._session_factory() as session:
            documents = await self._document_repository.list_documents(
                session,
                organization_id=organization_id,
                status=status_filter,
                filename_query=query,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            total = await self._document_repository.count_documents(
                session,
                organization_id=organization_id,
                status=status_filter,
                filename_query=query,
            )

            items: list[dict[str, Any]] = []
            for document in documents:
                chunk_count = await self._document_repository.count_document_chunks(
                    session,
                    document_id=document.id,
                    index_version=settings.document_index_version,
                )
                safe_error_message, safe_error_details = _safe_document_error(document)
                items.append(
                    {
                        "document_id": str(document.id),
                        "filename": document.filename,
                        "file_type": document.file_type,
                        "status": document.status,
                        "page_count": document.page_count,
                        "chunk_count": chunk_count,
                        "error_message": safe_error_message,
                        "error_details": safe_error_details,
                        "created_at": _ensure_iso(document.created_at),
                        "updated_at": _ensure_iso(document.updated_at),
                    }
                )

        return {
            "query": query,
            "status": status_filter,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "limit": limit,
            "offset": offset,
            "total": total,
            "items": items,
        }

    async def get_document_detail(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        organization_id = self._organization_uuid(principal)
        document_id = self._parse_document_id(
            call.arguments.get("document_id"), field_name="document_id"
        )

        async with self._session_factory() as session:
            document = await self._get_accessible_document(
                session=session,
                organization_id=organization_id,
                document_id=document_id,
            )
            chunk_count = await self._document_repository.count_document_chunks(
                session,
                document_id=document.id,
                index_version=settings.document_index_version,
            )

        safe_error_message, safe_error_details = _safe_document_error(document)
        return {
            "document": {
                "document_id": str(document.id),
                "filename": document.filename,
                "file_type": document.file_type,
                "status": document.status,
                "checksum": document.checksum,
                "page_count": document.page_count,
                "chunk_count": chunk_count,
                "error_message": safe_error_message,
                "error_details": safe_error_details,
                "created_at": _ensure_iso(document.created_at),
                "updated_at": _ensure_iso(document.updated_at),
            }
        }

    async def list_document_chunks(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        organization_id = self._organization_uuid(principal)
        arguments = call.arguments
        document_id = self._parse_document_id(
            arguments.get("document_id"), field_name="document_id"
        )
        limit = _coerce_int(
            arguments.get("limit"), field_name="limit", default=20, minimum=1, maximum=200
        )
        offset = _coerce_int(
            arguments.get("offset"), field_name="offset", default=0, minimum=0, maximum=100000
        )

        async with self._session_factory() as session:
            document = await self._get_accessible_document(
                session=session,
                organization_id=organization_id,
                document_id=document_id,
            )
            chunks = await self._document_repository.list_document_chunks_paginated(
                session,
                document_id=document.id,
                index_version=settings.document_index_version,
                limit=limit,
                offset=offset,
            )
            total = await self._document_repository.count_document_chunks(
                session,
                document_id=document.id,
                index_version=settings.document_index_version,
            )

        return {
            "document_id": str(document.id),
            "status": document.status,
            "limit": limit,
            "offset": offset,
            "total": total,
            "items": [
                {
                    "chunk_id": str(chunk.id),
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "token_count": chunk.token_count,
                    "embedding_model": chunk.embedding_model,
                    "index_version": chunk.index_version,
                    "preview": _chunk_preview_text(chunk.text),
                    "created_at": _ensure_iso(chunk.created_at),
                }
                for chunk in chunks
            ],
        }

    async def answer_from_context(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        arguments = call.arguments
        question = _coerce_non_empty_string(arguments.get("question"), field_name="question")
        top_k = _coerce_int(
            arguments.get("top_k"),
            field_name="top_k",
            default=settings.retrieval_final_top_k,
            minimum=1,
            maximum=settings.retrieval_initial_top_k,
        )
        rerank = _coerce_bool(arguments.get("rerank"), field_name="rerank", default=True)
        document_ids = await self._resolve_accessible_document_ids(
            document_ids=arguments.get("document_ids"),
            principal=principal,
            require_indexed=True,
        )

        return await self._run_grounded_answer(
            question=question,
            principal=principal,
            document_ids=document_ids,
            top_k=top_k,
            rerank=rerank,
        )

    async def summarize_document(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        arguments = call.arguments
        document_id = self._parse_document_id(
            arguments.get("document_id"), field_name="document_id"
        )
        top_k = _coerce_int(
            arguments.get("top_k"),
            field_name="top_k",
            default=min(8, settings.retrieval_initial_top_k),
            minimum=1,
            maximum=settings.retrieval_initial_top_k,
        )
        rerank = _coerce_bool(arguments.get("rerank"), field_name="rerank", default=True)

        async with self._session_factory() as session:
            document = await self._get_accessible_document(
                session=session,
                organization_id=self._organization_uuid(principal),
                document_id=document_id,
            )
        question = (
            "Provide a grounded summary with key points and risks. "
            f"Focus on the document: {document.filename}"
        )
        result = await self._run_grounded_answer(
            question=question,
            principal=principal,
            document_ids=[document_id],
            top_k=top_k,
            rerank=rerank,
        )
        return {
            "document_id": str(document_id),
            "summary": result["response"],
            "not_found": result["not_found"],
            "confidence": result["confidence"],
            "citations": result["citations"],
            "debug": result["debug"],
        }

    async def compare_documents(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        arguments = call.arguments
        top_k = _coerce_int(
            arguments.get("top_k"),
            field_name="top_k",
            default=min(12, settings.retrieval_initial_top_k),
            minimum=1,
            maximum=settings.retrieval_initial_top_k,
        )
        rerank = _coerce_bool(arguments.get("rerank"), field_name="rerank", default=True)
        document_ids = await self._resolve_accessible_document_ids(
            document_ids=arguments.get("document_ids"),
            principal=principal,
            require_indexed=True,
        )
        if len(document_ids) < 2:
            raise ValueError("document_ids must contain at least two documents")

        async with self._session_factory() as session:
            organization_id = self._organization_uuid(principal)
            documents = []
            for document_id in document_ids:
                documents.append(
                    await self._get_accessible_document(
                        session=session,
                        organization_id=organization_id,
                        document_id=document_id,
                    )
                )

        default_question = (
            "Compare these documents. Include key similarities, key differences, contradictions, "
            "and a concise risk summary."
        )
        question = (
            _coerce_optional_string(arguments.get("question"), field_name="question")
            or default_question
        )
        result = await self._run_grounded_answer(
            question=question,
            principal=principal,
            document_ids=document_ids,
            top_k=top_k,
            rerank=rerank,
        )
        return {
            "document_ids": [str(document_id) for document_id in document_ids],
            "filenames": [document.filename for document in documents],
            "comparison": result["response"],
            "not_found": result["not_found"],
            "confidence": result["confidence"],
            "citations": result["citations"],
            "debug": result["debug"],
        }

    def _organization_uuid(self, principal: AuthenticatedPrincipal) -> UUID:
        if principal.organization_id is None:
            raise AuthorizationError("No active organization context for principal")
        try:
            return UUID(principal.organization_id)
        except ValueError as exc:
            raise AuthorizationError("Principal organization context is invalid") from exc

    def _parse_document_id(self, value: object, *, field_name: str) -> UUID:
        parsed_value = _coerce_non_empty_string(value, field_name=field_name)
        try:
            return UUID(parsed_value)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a valid UUID") from exc

    async def _resolve_accessible_document_ids(
        self,
        *,
        document_ids: object,
        principal: AuthenticatedPrincipal,
        require_indexed: bool,
    ) -> list[UUID]:
        if document_ids is None:
            return []
        if not isinstance(document_ids, list):
            raise ValueError("document_ids must be an array of UUID strings")
        parsed_ids: list[UUID] = []
        seen: set[UUID] = set()
        for raw_id in document_ids:
            document_id = self._parse_document_id(raw_id, field_name="document_ids[]")
            if document_id in seen:
                continue
            seen.add(document_id)
            parsed_ids.append(document_id)

        async with self._session_factory() as session:
            organization_id = self._organization_uuid(principal)
            for document_id in parsed_ids:
                document = await self._get_accessible_document(
                    session=session,
                    organization_id=organization_id,
                    document_id=document_id,
                )
                if require_indexed and document.status != DocumentStatus.indexed.value:
                    raise AuthorizationError("Document is not indexed or not accessible")

        return parsed_ids

    async def _get_accessible_document(
        self,
        *,
        session: AsyncSession,
        organization_id: UUID,
        document_id: UUID,
    ) -> Document:
        document = await self._document_repository.get_document(
            session,
            document_id=document_id,
            organization_id=organization_id,
        )
        if document is None:
            raise AuthorizationError("Document not found or inaccessible")
        return document

    def _resolve_qdrant_client(self) -> Any:
        if self._qdrant_client is None:
            if qdrant_module.qdrant_client is None:
                qdrant_module.init_qdrant()
            if qdrant_module.qdrant_client is None:
                raise RuntimeError("Qdrant client is not initialized")
            self._qdrant_client = qdrant_module.qdrant_client
        return self._qdrant_client

    async def _rerank_chunks(
        self,
        *,
        query: str,
        chunks: list[_RetrievedChunk],
        enabled: bool,
        final_top_k: int,
    ) -> list[_RetrievedChunk]:
        if final_top_k < 1 or not chunks:
            return []

        chunk_by_key = {str(chunk.chunk_id): chunk for chunk in chunks}
        rerank_inputs = [
            RerankCandidate(
                key=str(chunk.chunk_id),
                text=chunk.text,
                similarity_score=chunk.similarity_score,
            )
            for chunk in chunks
        ]
        rerank_result = await self._rerank_service.rerank(
            query=query,
            candidates=rerank_inputs,
            enabled=enabled,
            final_top_k=final_top_k,
        )

        selected: list[_RetrievedChunk] = []
        for reranked in rerank_result.candidates:
            source = chunk_by_key.get(reranked.key)
            if source is None:
                continue
            selected.append(
                _RetrievedChunk(
                    document_id=source.document_id,
                    chunk_id=source.chunk_id,
                    filename=source.filename,
                    page_number=source.page_number,
                    text=source.text,
                    similarity_score=source.similarity_score,
                    rerank_score=reranked.rerank_score,
                    rerank_rank=reranked.rerank_rank,
                )
            )
        return selected

    async def _run_grounded_answer(
        self,
        *,
        question: str,
        principal: AuthenticatedPrincipal,
        document_ids: list[UUID],
        top_k: int,
        rerank: bool,
    ) -> dict[str, Any]:
        organization_id = self._organization_uuid(principal)
        retrieval_top_k = max(top_k, self._rerank_service.candidate_count if rerank else top_k)
        started_total = perf_counter()

        # Resolve the org's agentic model profile for provider-neutral routing.
        agentic_profile = None
        try:
            async with self._session_factory() as profile_session:
                agentic_profile = await resolve_task_profile(
                    profile_session,
                    organization_id=organization_id,
                    task_type=TaskType.agentic,
                )
        except Exception:
            pass  # Fall back to LLMService defaults on resolution failure.

        retrieval_result = await self._query_retrieval_service.embed_and_retrieve(
            question=question,
            organization_id=organization_id,
            document_ids=document_ids,
            initial_top_k=retrieval_top_k,
            qdrant_client=self._qdrant_client,
        )
        retrieved_chunks = [
            _to_retrieved_chunk(candidate) for candidate in retrieval_result.candidates
        ]
        selected_chunks = await self._rerank_chunks(
            query=question,
            chunks=retrieved_chunks,
            enabled=rerank,
            final_top_k=top_k,
        )
        embedding_tokens = retrieval_result.embedding_prompt_tokens
        embedding_cost_usd = (
            embedding_tokens / 1_000_000
        ) * settings.openai_embedding_cost_per_million_tokens_usd

        confidence_signals = [
            ConfidenceChunkSignal(
                similarity_score=chunk.similarity_score,
                rerank_score=chunk.rerank_score if rerank else None,
            )
            for chunk in selected_chunks
        ]
        confidence_result = self._confidence_service.score(
            chunks=confidence_signals,
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=False,
        )
        not_found = (
            len(selected_chunks) == 0
            or confidence_result.score < settings.confidence_not_found_threshold
        )
        if not_found:
            confidence_result = self._confidence_service.score(
                chunks=confidence_signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=True,
            )
            return {
                "response": _NOT_FOUND_RESPONSE,
                "not_found": True,
                "citations": [],
                "confidence": {
                    "score": confidence_result.score,
                    "category": confidence_result.category,
                    "explanation": confidence_result.explanation.__dict__,
                },
                "debug": {
                    "retrieval_count": len(retrieved_chunks),
                    "selected_count": len(selected_chunks),
                    "rerank_applied": rerank,
                    "embedding_model": retrieval_result.embedding_model,
                    "llm_model": None,
                    "provider_key": agentic_profile.provider_type
                    if agentic_profile is not None
                    else None,
                    "provider_type": agentic_profile.provider_type
                    if agentic_profile is not None
                    else None,
                    "usage": {
                        "embedding_prompt_tokens": embedding_tokens,
                        "llm_prompt_tokens": 0,
                        "llm_completion_tokens": 0,
                        "total_tokens": embedding_tokens,
                        "embedding_cost_usd": embedding_cost_usd,
                        "llm_cost_usd": 0.0,
                        "total_cost_usd": embedding_cost_usd,
                    },
                    "latency_ms_total": int((perf_counter() - started_total) * 1000),
                },
            }

        prompt = self._prompt_service.build_prompt(
            question=question,
            not_found_answer=_NOT_FOUND_RESPONSE,
            chunks=[
                PromptContextChunk(
                    document_id=str(chunk.document_id),
                    chunk_id=str(chunk.chunk_id),
                    filename=chunk.filename,
                    page_number=chunk.page_number,
                    text=chunk.text,
                    similarity_score=chunk.similarity_score,
                    rerank_score=chunk.rerank_score,
                    rerank_rank=chunk.rerank_rank,
                )
                for chunk in selected_chunks
            ],
        )

        try:
            llm_result = await self._llm_service.generate_answer(
                prompt=prompt,
                resolved_profile=agentic_profile,
            )
        except (TransientLLMServiceError, PermanentLLMServiceError) as exc:
            raise RuntimeError("LLM answer generation failed") from exc

        response_text = llm_result.answer.strip()
        llm_not_found = (
            llm_result.not_found or not response_text or response_text == _NOT_FOUND_RESPONSE
        )
        if llm_not_found:
            confidence_result = self._confidence_service.score(
                chunks=confidence_signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=True,
            )
            return {
                "response": _NOT_FOUND_RESPONSE,
                "not_found": True,
                "citations": [],
                "confidence": {
                    "score": confidence_result.score,
                    "category": confidence_result.category,
                    "explanation": confidence_result.explanation.__dict__,
                },
                "debug": {
                    "retrieval_count": len(retrieved_chunks),
                    "selected_count": len(selected_chunks),
                    "rerank_applied": rerank,
                    "embedding_model": retrieval_result.embedding_model,
                    "llm_model": llm_result.model_name,
                    "provider_key": llm_result.provider_key,
                    "provider_type": agentic_profile.provider_type
                    if agentic_profile is not None
                    else None,
                    "usage": {
                        "embedding_prompt_tokens": embedding_tokens,
                        "llm_prompt_tokens": llm_result.prompt_tokens,
                        "llm_completion_tokens": llm_result.completion_tokens,
                        "total_tokens": embedding_tokens + llm_result.total_tokens,
                        "embedding_cost_usd": embedding_cost_usd,
                        "llm_cost_usd": float(llm_result.approximate_cost_usd),
                        "total_cost_usd": embedding_cost_usd
                        + float(llm_result.approximate_cost_usd),
                    },
                    "latency_ms_total": int((perf_counter() - started_total) * 1000),
                },
            }

        citation_result = self._citation_service.build_citations(
            not_found=False,
            answer=response_text,
            retrieved_chunks=[
                CitationContextChunk(
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    filename=chunk.filename,
                    page_number=chunk.page_number,
                    text=chunk.text,
                    similarity_score=chunk.similarity_score,
                    rerank_score=chunk.rerank_score,
                    rerank_rank=chunk.rerank_rank,
                )
                for chunk in selected_chunks
            ],
            model_citations=llm_result.citations,
        )
        confidence_result = self._confidence_service.score(
            chunks=confidence_signals,
            citation_count=len(citation_result.citations),
            citation_validation_score=citation_result.validation_score,
            not_found_signal=False,
        )

        return {
            "response": response_text,
            "not_found": False,
            "citations": [
                {
                    "document_id": citation.document_id,
                    "chunk_id": citation.chunk_id,
                    "filename": citation.filename,
                    "page_number": citation.page_number,
                    "score": citation.score,
                    "similarity_score": citation.similarity_score,
                    "rerank_score": citation.rerank_score if rerank else None,
                    "rerank_rank": citation.rerank_rank,
                    "snippet": citation.text_snippet,
                }
                for citation in citation_result.citations
            ],
            "confidence": {
                "score": confidence_result.score,
                "category": _category_from_score(confidence_result.score),
                "explanation": confidence_result.explanation.__dict__,
            },
            "debug": {
                "retrieval_count": len(retrieved_chunks),
                "selected_count": len(selected_chunks),
                "rerank_applied": rerank,
                "embedding_model": retrieval_result.embedding_model,
                "llm_model": llm_result.model_name,
                "provider_key": llm_result.provider_key,
                "provider_type": agentic_profile.provider_type
                if agentic_profile is not None
                else None,
                "citation_validation_score": citation_result.validation_score,
                "usage": {
                    "embedding_prompt_tokens": embedding_tokens,
                    "llm_prompt_tokens": llm_result.prompt_tokens,
                    "llm_completion_tokens": llm_result.completion_tokens,
                    "total_tokens": embedding_tokens + llm_result.total_tokens,
                    "embedding_cost_usd": embedding_cost_usd,
                    "llm_cost_usd": float(llm_result.approximate_cost_usd),
                    "total_cost_usd": embedding_cost_usd + float(llm_result.approximate_cost_usd),
                },
                "latency_ms_total": int((perf_counter() - started_total) * 1000),
            },
        }


def register_document_intelligence_handlers(
    *,
    registry: ToolRegistry,
    service: DocumentIntelligenceToolService | None = None,
) -> DocumentIntelligenceToolService:
    resolved_service = service or DocumentIntelligenceToolService()
    registry.register_handler(
        tool_name="search_documents", handler=resolved_service.search_documents
    )
    registry.register_handler(
        tool_name="get_document_detail", handler=resolved_service.get_document_detail
    )
    registry.register_handler(
        tool_name="list_document_chunks", handler=resolved_service.list_document_chunks
    )
    registry.register_handler(
        tool_name="answer_from_context", handler=resolved_service.answer_from_context
    )
    registry.register_handler(
        tool_name="summarize_document", handler=resolved_service.summarize_document
    )
    registry.register_handler(
        tool_name="compare_documents", handler=resolved_service.compare_documents
    )
    return resolved_service
