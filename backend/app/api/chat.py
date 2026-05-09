from dataclasses import dataclass
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.core.logging import log_query_event
from app.db.session import get_db_session
from app.models.enums import ChatRole, OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    ChatCitationResponse,
    ChatDebugResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatSessionListResponse,
    ChatSessionResponse,
    CreateChatSessionRequest,
)
from app.services.llm_service import LLMService, PermanentLLMServiceError, TransientLLMServiceError
from app.services.prompt_service import PromptContextChunk, PromptService
from app.services.query_retrieval_service import QueryRetrievalService, RetrievedCandidate
from app.services.rerank_service import RerankCandidate, RerankService

router = APIRouter(prefix="/chat", tags=["chat"])
chat_repository = ChatRepository()
_openai_client: AsyncOpenAI | None = None
_query_retrieval_service = QueryRetrievalService()
_rerank_service = RerankService()
_prompt_service = PromptService()
_llm_service = LLMService()
_NOT_FOUND_ANSWER = "I could not find this information in the uploaded documents."
_LOW_CONFIDENCE_THRESHOLD = 0.20


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: UUID
    chunk_id: UUID
    filename: str
    page_number: int | None
    text: str
    similarity_score: float
    rerank_score: float | None = None
    rerank_rank: int | None = None


def _safe_http_error(*, status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
        },
    )


def _principal_user_and_org(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.user_id), UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        if settings.openai_api_key is None:
            raise RuntimeError("OpenAI API key is not configured")
        timeout_seconds = max(
            settings.dependency_connect_timeout_seconds,
            settings.dependency_read_timeout_seconds,
        )
        _openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=timeout_seconds,
            max_retries=0,
        )
    return _openai_client


def _get_qdrant_client():
    if qdrant_module.qdrant_client is None:
        qdrant_module.init_qdrant()
    if qdrant_module.qdrant_client is None:
        raise RuntimeError("Qdrant client is not initialized")
    return qdrant_module.qdrant_client


def _to_retrieved_chunk(candidate: RetrievedCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
    )


def _rerank_chunks(
    *,
    chunks: list[RetrievedChunk],
    enabled: bool,
    final_top_k: int,
) -> list[RetrievedChunk]:
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

    rerank_results = _rerank_service.rerank(
        candidates=rerank_inputs,
        enabled=enabled,
        final_top_k=final_top_k,
    )

    selected_chunks: list[RetrievedChunk] = []
    for reranked in rerank_results:
        source_chunk = chunk_by_key.get(reranked.key)
        if source_chunk is None:
            continue
        selected_chunks.append(
            RetrievedChunk(
                document_id=source_chunk.document_id,
                chunk_id=source_chunk.chunk_id,
                filename=source_chunk.filename,
                page_number=source_chunk.page_number,
                text=source_chunk.text,
                similarity_score=source_chunk.similarity_score,
                rerank_score=reranked.rerank_score,
                rerank_rank=reranked.rerank_rank,
            )
        )
    return selected_chunks


def _build_prompt(*, question: str, chunks: list[RetrievedChunk]) -> str:
    return _prompt_service.build_prompt(
        question=question,
        not_found_answer=_NOT_FOUND_ANSWER,
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
            for chunk in chunks
        ],
    )


def _build_citations(chunks: list[RetrievedChunk]) -> list[ChatCitationResponse]:
    return [
        ChatCitationResponse(
            document_id=str(chunk.document_id),
            chunk_id=str(chunk.chunk_id),
            filename=chunk.filename,
            page_number=chunk.page_number,
            score=chunk.rerank_score if chunk.rerank_score is not None else chunk.similarity_score,
            similarity_score=chunk.similarity_score,
            rerank_score=chunk.rerank_score,
            rerank_rank=chunk.rerank_rank,
            text_snippet=chunk.text[:400],
        )
        for chunk in chunks
    ]


def _score_confidence(*, chunks: list[RetrievedChunk], rerank_applied: bool) -> float:
    if not chunks:
        return 0.0

    top_similarity = max(0.0, min(1.0, chunks[0].similarity_score))
    if not rerank_applied:
        return round(top_similarity, 4)

    top_rerank = max(0.0, min(1.0, chunks[0].rerank_score or 0.0))
    combined = (0.6 * top_similarity) + (0.4 * top_rerank)
    return round(max(0.0, min(1.0, combined)), 4)


@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_chat_session(
    payload: CreateChatSessionRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    title = payload.title.strip() if payload.title is not None else None

    chat_session = await chat_repository.create_chat_session(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        title=title,
    )
    await db_session.commit()
    await db_session.refresh(chat_session)

    log_query_event(
        event="chat.session.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(chat_session.id),
        status_code=status.HTTP_201_CREATED,
    )
    return ChatSessionResponse(
        session_id=str(chat_session.id),
        title=chat_session.title,
        message_count=0,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_chat_sessions(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatSessionListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    sessions = await chat_repository.list_chat_sessions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    total = await chat_repository.count_chat_sessions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
    )
    message_counts = await chat_repository.count_messages_by_session_ids(
        db_session,
        session_ids=[session.id for session in sessions],
    )

    items = [
        ChatSessionResponse(
            session_id=str(chat_session.id),
            title=chat_session.title,
            message_count=message_counts.get(chat_session.id, 0),
            created_at=chat_session.created_at,
            updated_at=chat_session.updated_at,
        )
        for chat_session in sessions
    ]

    log_query_event(
        event="chat.session.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
    )
    return ChatSessionListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(
    session_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatSessionResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found") from exc

    chat_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if chat_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    message_counts = await chat_repository.count_messages_by_session_ids(
        db_session,
        session_ids=[chat_session.id],
    )

    log_query_event(
        event="chat.session.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_200_OK,
    )
    return ChatSessionResponse(
        session_id=str(chat_session.id),
        title=chat_session.title,
        message_count=message_counts.get(chat_session.id, 0),
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )


@router.post("", response_model=ChatQueryResponse)
async def query_chat(
    payload: ChatQueryRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatQueryResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    try:
        document_ids = await ensure_document_ids_access(
            document_ids=payload.document_ids,
            principal=principal,
            db_session=db_session,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            log_query_event(
                event="query.rejected.document_not_found",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                status_code=status.HTTP_404_NOT_FOUND,
            )
            raise _safe_http_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="document_not_found",
                message="Document not found",
            ) from exc
        raise

    if payload.chat_session_id is not None:
        try:
            chat_session_id = UUID(payload.chat_session_id)
        except ValueError as exc:
            log_query_event(
                event="query.rejected.chat_session_not_found",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                status_code=status.HTTP_404_NOT_FOUND,
            )
            raise _safe_http_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="chat_session_not_found",
                message="Chat session not found",
            ) from exc
        chat_session = await chat_repository.get_chat_session(
            db_session,
            chat_session_id=chat_session_id,
            organization_id=organization_id,
            user_id=user_id,
        )
        if chat_session is None:
            log_query_event(
                event="query.rejected.chat_session_not_found",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                status_code=status.HTTP_404_NOT_FOUND,
            )
            raise _safe_http_error(
                status_code=status.HTTP_404_NOT_FOUND,
                code="chat_session_not_found",
                message="Chat session not found",
            )
    else:
        default_title = payload.question[:120]
        chat_session = await chat_repository.create_chat_session(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            title=default_title,
        )

    final_top_k = payload.top_k or settings.retrieval_final_top_k
    retrieval_top_k = max(
        final_top_k,
        _rerank_service.candidate_count if payload.rerank else final_top_k,
    )

    latencies_ms: dict[str, int] = {}
    total_started = perf_counter()
    embedding_model = _query_retrieval_service.embedding_model

    embed_started = perf_counter()
    try:
        query_vector, embedding_prompt_tokens = await _query_retrieval_service.embed_query(
            question=payload.question,
            openai_client=_get_openai_client(),
        )
    except Exception as exc:
        log_query_event(
            event="query.failed.embed",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=str(chat_session.id),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
            embedding_model=embedding_model,
        )
        raise _safe_http_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="query_embedding_failed",
            message="Query embedding is unavailable",
        ) from exc
    latencies_ms["embed"] = int((perf_counter() - embed_started) * 1000)

    retrieve_started = perf_counter()
    try:
        retrieved_candidates = _query_retrieval_service.retrieve_candidates(
            query_vector=query_vector,
            organization_id=organization_id,
            document_ids=document_ids,
            initial_top_k=retrieval_top_k,
            qdrant_client=_get_qdrant_client(),
        )
        retrieved_chunks = [_to_retrieved_chunk(candidate) for candidate in retrieved_candidates]
    except Exception as exc:
        log_query_event(
            event="query.failed.retrieve",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=str(chat_session.id),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error=exc.__class__.__name__,
            initial_top_k=retrieval_top_k,
        )
        raise _safe_http_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="retrieval_failed",
            message="Retrieval is unavailable",
        ) from exc
    latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)

    rerank_started = perf_counter()
    selected_chunks = _rerank_chunks(
        chunks=retrieved_chunks,
        enabled=payload.rerank,
        final_top_k=final_top_k,
    )
    latencies_ms["rerank"] = int((perf_counter() - rerank_started) * 1000)

    llm_prompt_tokens = 0
    llm_completion_tokens = 0
    llm_model: str | None = None
    llm_cost_usd = None

    confidence_score = _score_confidence(chunks=selected_chunks, rerank_applied=payload.rerank)
    not_found = len(selected_chunks) == 0 or confidence_score < _LOW_CONFIDENCE_THRESHOLD

    prompt_started = perf_counter()
    prompt = _build_prompt(question=payload.question, chunks=selected_chunks) if not not_found else ""
    latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

    answer = _NOT_FOUND_ANSWER
    citations: list[ChatCitationResponse] = []

    llm_latency_ms = 0
    if not not_found:
        try:
            llm_result = await _llm_service.generate_answer(
                prompt=prompt,
                openai_client=_get_openai_client(),
            )
        except (TransientLLMServiceError, PermanentLLMServiceError) as exc:
            log_query_event(
                event="query.failed.generate",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                job_id=str(chat_session.id),
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                error=exc.__class__.__name__,
            )
            raise _safe_http_error(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="generation_failed",
                message="Answer generation is unavailable",
            ) from exc

        llm_latency_ms = llm_result.latency_ms
        llm_model = llm_result.model_name
        llm_prompt_tokens = llm_result.prompt_tokens
        llm_completion_tokens = llm_result.completion_tokens
        llm_cost_usd = llm_result.approximate_cost_usd
        answer = llm_result.answer

        if llm_result.not_found:
            answer = _NOT_FOUND_ANSWER
            not_found = True
        elif not answer.strip() or answer.strip() == _NOT_FOUND_ANSWER:
            answer = _NOT_FOUND_ANSWER
            not_found = True
        else:
            citations = _build_citations(selected_chunks)
    latencies_ms["llm"] = llm_latency_ms

    persist_started = perf_counter()
    try:
        _ = await chat_repository.create_chat_message(
            db_session,
            chat_session_id=chat_session.id,
            role=ChatRole.user.value,
            content=payload.question,
        )
        assistant_message = await chat_repository.create_chat_message(
            db_session,
            chat_session_id=chat_session.id,
            role=ChatRole.assistant.value,
            content=answer,
            confidence_score=confidence_score,
            model_name=llm_model,
            token_input_count=embedding_prompt_tokens + llm_prompt_tokens,
            token_output_count=llm_completion_tokens,
            cost_usd=llm_cost_usd,
        )

        for citation in citations:
            await chat_repository.create_citation(
                db_session,
                chat_message_id=assistant_message.id,
                document_id=UUID(citation.document_id),
                chunk_id=UUID(citation.chunk_id),
                text_snippet=citation.text_snippet or "",
                page_number=citation.page_number,
                similarity_score=citation.similarity_score,
                rerank_score=citation.rerank_score if payload.rerank else None,
            )

        await db_session.commit()
    except Exception as exc:
        await db_session.rollback()
        log_query_event(
            event="query.failed.persist",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=str(chat_session.id),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error=exc.__class__.__name__,
        )
        raise _safe_http_error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="chat_persistence_failed",
            message="Failed to persist chat response",
        ) from exc
    latencies_ms["persist"] = int((perf_counter() - persist_started) * 1000)

    latencies_ms["total"] = int((perf_counter() - total_started) * 1000)

    log_query_event(
        event="query.completed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(chat_session.id),
        status_code=status.HTTP_200_OK,
        not_found=not_found,
        confidence_score=confidence_score,
        retrieval_count=len(retrieved_chunks),
        selected_count=len(selected_chunks),
    )
    return ChatQueryResponse(
        chat_session_id=str(chat_session.id),
        message_id=str(assistant_message.id),
        answer=answer,
        confidence_score=confidence_score,
        not_found=not_found,
        citations=[] if not_found else citations,
        debug=ChatDebugResponse(
            latencies_ms=latencies_ms,
            retrieval_count=len(retrieved_chunks),
            selected_count=len(selected_chunks),
            rerank_applied=payload.rerank,
            embedding_model=embedding_model,
            llm_model=llm_model,
        ),
        created_at=assistant_message.created_at,
    )


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse)
async def create_chat_message(
    session_id: str,
    payload: ChatMessageRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    _: Annotated[None, Depends(enforce_rate_limit(RateLimitScope.chat))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ChatMessageResponse:
    await ensure_document_ids_access(
        document_ids=payload.document_ids,
        principal=principal,
        db_session=db_session,
    )

    log_query_event(
        event="query.requested",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Chat pipeline for session {session_id} is not implemented in scaffold.",
    )
