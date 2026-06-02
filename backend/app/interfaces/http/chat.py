import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.core.logging import log_query_event
from app.db.session import get_db_session
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.chat.repositories.feedback import FeedbackRepository
from app.domains.chat.repositories.share import ChatShareRepository
from app.domains.chat.schemas.chat import (
    ChatCitationResponse,
    ChatConfidenceExplanationResponse,
    ChatDebugResponse,
    ChatMessageRequest,
    ChatMessageResponse,
    ChatQueryRequest,
    ChatQueryResponse,
    ChatSessionListResponse,
    ChatSessionMessageListResponse,
    ChatSessionMessageResponse,
    ChatSessionResponse,
    CreateChatSessionRequest,
    UpdateChatSessionRequest,
)
from app.domains.chat.schemas.feedback import (
    MessageFeedbackResponse,
    SessionFeedbackListResponse,
    SubmitFeedbackRequest,
)
from app.domains.chat.schemas.share import (
    ChatShareListResponse,
    ChatShareResponse,
    CreateChatShareRequest,
    SharedSessionResponse,
)
from app.core.safety_guardrails import PromptInjectionGuard
from app.domains.chat.services.citation_service import CitationContextChunk, CitationService
from app.domains.chat.services.confidence_service import ConfidenceChunkSignal, ConfidenceService
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
from app.models.enums import ChatRole, OrganizationRole
from app.rate_limit import RateLimitScope, enforce_rate_limit

router = APIRouter(prefix="/chat", tags=["chat"])
chat_repository = ChatRepository()
share_repository = ChatShareRepository()
feedback_repository = FeedbackRepository()
usage_repository = UsageRepository()
audit_log_service = AuditLogService()

_MAX_ACTIVE_SHARES_PER_SESSION = 10
_openai_client: AsyncOpenAI | None = None
_query_retrieval_service = QueryRetrievalService()
_rerank_service = RerankService()
_prompt_service = PromptService()
_citation_service = CitationService()
_confidence_service = ConfidenceService()
_llm_service = LLMService()
_injection_guard = PromptInjectionGuard()
_NOT_FOUND_ANSWER = "I could not find this information in the uploaded documents."


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
            float(settings.request_timeout_seconds), settings.dependency_read_timeout_seconds
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


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


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


def _to_confidence_signals(
    *, chunks: list[RetrievedChunk], rerank_applied: bool
) -> list[ConfidenceChunkSignal]:
    return [
        ConfidenceChunkSignal(
            similarity_score=chunk.similarity_score,
            rerank_score=chunk.rerank_score if rerank_applied else None,
        )
        for chunk in chunks
    ]


def _confidence_category_from_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= settings.confidence_high_threshold:
        return "high"
    if score >= settings.confidence_medium_threshold:
        return "medium"
    return "low"


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
    search: Annotated[str | None, Query(max_length=255)] = None,
) -> ChatSessionListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    normalized_search = search.strip() if search and search.strip() else None
    sessions = await chat_repository.list_chat_sessions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
        search=normalized_search,
    )
    total = await chat_repository.count_chat_sessions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        search=normalized_search,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

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


@router.get("/sessions/{session_id}/messages", response_model=ChatSessionMessageListResponse)
async def list_chat_session_messages(
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
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatSessionMessageListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    chat_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if chat_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    messages = await chat_repository.list_chat_messages(
        db_session,
        chat_session_id=chat_session.id,
        limit=limit,
        offset=offset,
    )
    total = await chat_repository.count_chat_messages(
        db_session,
        chat_session_id=chat_session.id,
    )

    items: list[ChatSessionMessageResponse] = []
    for message in messages:
        message_citations: list[ChatCitationResponse] = []
        if message.role == ChatRole.assistant.value:
            citation_rows = await chat_repository.list_citations_for_message_with_filename(
                db_session,
                chat_message_id=message.id,
            )
            message_citations = [
                ChatCitationResponse(
                    document_id=str(citation.document_id),
                    chunk_id=str(citation.chunk_id),
                    filename=filename,
                    page_number=citation.page_number,
                    score=citation.rerank_score
                    if citation.rerank_score is not None
                    else citation.similarity_score,
                    similarity_score=citation.similarity_score,
                    rerank_score=citation.rerank_score,
                    rerank_rank=None,
                    text_snippet=citation.text_snippet,
                    start_offset=citation.start_offset,
                    end_offset=citation.end_offset,
                )
                for citation, filename in citation_rows
            ]

        items.append(
            ChatSessionMessageResponse(
                message_id=str(message.id),
                role=message.role,
                content=message.content,
                confidence_score=message.confidence_score,
                confidence_category=_confidence_category_from_score(message.confidence_score),
                citations=message_citations,
                created_at=message.created_at,
            )
        )

    log_query_event(
        event="chat.session.messages.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
    )
    return ChatSessionMessageListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ChatQueryResponse)
async def query_chat(
    request: Request,
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
    request_id = _request_id_from_request(request)
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

    injection_check = _injection_guard.evaluate_request(
        objective="",
        question=payload.question,
        document_query=None,
    )
    if injection_check.blocked:
        log_query_event(
            event="query.rejected.question_injection_detected",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=str(chat_session.id),
            status_code=status.HTTP_200_OK,
            reasons=injection_check.reasons,
        )

    latencies_ms: dict[str, int] = {}
    total_started = perf_counter()
    embedding_model = _query_retrieval_service.embedding_model

    retrieved_chunks: list[RetrievedChunk] = []
    selected_chunks: list[RetrievedChunk] = []
    embedding_prompt_tokens = 0
    llm_prompt_tokens = 0
    llm_completion_tokens = 0
    llm_model: str | None = None
    llm_cost_usd = None
    llm_latency_ms = 0
    answer = _NOT_FOUND_ANSWER
    citations: list[ChatCitationResponse] = []
    not_found = injection_check.blocked
    citation_validation_failed = False

    if injection_check.blocked:
        # Question matched injection heuristics: return safe not-found without LLM call.
        embedding_model = None
        confidence_signals = _to_confidence_signals(chunks=[], rerank_applied=False)
        confidence_result = _confidence_service.score(
            chunks=confidence_signals,
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=True,
        )
        confidence_score = confidence_result.score
        confidence_category = confidence_result.category
        confidence_explanation = confidence_result.explanation
    elif payload.scope_mode == "none":
        # General chat mode: skip retrieval, answer from LLM general knowledge.
        embedding_model = None
        prompt = _prompt_service.build_general_prompt(question=payload.question)
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
        answer = llm_result.answer if llm_result.answer.strip() else _NOT_FOUND_ANSWER
        not_found = llm_result.not_found or not answer.strip()
        confidence_signals = _to_confidence_signals(chunks=[], rerank_applied=False)
        confidence_result = _confidence_service.score(
            chunks=confidence_signals,
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=not_found,
        )
        confidence_score = confidence_result.score
        confidence_category = confidence_result.category
        confidence_explanation = confidence_result.explanation
    else:
        final_top_k = payload.top_k or settings.retrieval_final_top_k
        retrieval_top_k = max(
            final_top_k,
            _rerank_service.candidate_count if payload.rerank else final_top_k,
        )

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
            retrieved_chunks = [
                _to_retrieved_chunk(candidate) for candidate in retrieved_candidates
            ]
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

        confidence_signals = _to_confidence_signals(
            chunks=selected_chunks, rerank_applied=payload.rerank
        )
        confidence_result = _confidence_service.score(
            chunks=confidence_signals,
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=False,
        )
        confidence_score = confidence_result.score
        confidence_category = confidence_result.category
        confidence_explanation = confidence_result.explanation
        not_found = (
            len(selected_chunks) == 0 or confidence_score < settings.confidence_not_found_threshold
        )

        if not_found:
            confidence_result = _confidence_service.score(
                chunks=confidence_signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=True,
            )
            confidence_score = confidence_result.score
            confidence_category = confidence_result.category
            confidence_explanation = confidence_result.explanation

        prompt_started = perf_counter()
        prompt = (
            _build_prompt(question=payload.question, chunks=selected_chunks)
            if not not_found
            else ""
        )
        latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

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
                citation_result = _citation_service.build_citations(
                    not_found=False,
                    answer=answer,
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
                citations = citation_result.citations
                citation_validation_failed = citation_result.invalid_chunk_id_count > 0
                confidence_result = _confidence_service.score(
                    chunks=confidence_signals,
                    citation_count=len(citations),
                    citation_validation_score=citation_result.validation_score,
                    not_found_signal=False,
                )
                confidence_score = confidence_result.score
                confidence_category = confidence_result.category
                confidence_explanation = confidence_result.explanation
                log_query_event(
                    event="query.citations.validated",
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    job_id=str(chat_session.id),
                    validation_score=citation_result.validation_score,
                    model_citation_count=citation_result.model_citation_count,
                    accepted_model_citation_count=citation_result.accepted_model_citation_count,
                    used_fallback=citation_result.used_fallback,
                    invalid_chunk_id_count=citation_result.invalid_chunk_id_count,
                    metadata_mismatch_count=citation_result.metadata_mismatch_count,
                    snippet_mismatch_count=citation_result.snippet_mismatch_count,
                )
                if citation_validation_failed:
                    log_query_event(
                        event="query.citations.validation_failed",
                        organization_id=principal.organization_id,
                        user_id=principal.user_id,
                        job_id=str(chat_session.id),
                        invalid_chunk_id_count=citation_result.invalid_chunk_id_count,
                    )

            if not_found:
                confidence_result = _confidence_service.score(
                    chunks=confidence_signals,
                    citation_count=0,
                    citation_validation_score=1.0,
                    not_found_signal=True,
                )
                confidence_score = confidence_result.score
                confidence_category = confidence_result.category
                confidence_explanation = confidence_result.explanation

    latencies_ms["llm"] = llm_latency_ms
    answer_latency_ms = int((perf_counter() - total_started) * 1000)

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
            latency_ms=answer_latency_ms,
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
                start_offset=citation.start_offset,
                end_offset=citation.end_offset,
                similarity_score=citation.similarity_score,
                rerank_score=citation.rerank_score if payload.rerank else None,
            )

        await usage_repository.create_usage_event(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            event_type="chat.completion",
            model_name=llm_model,
            input_tokens=embedding_prompt_tokens + llm_prompt_tokens,
            output_tokens=llm_completion_tokens,
            cost_usd=llm_cost_usd,
            metadata={
                "chat_session_id": str(chat_session.id),
                "assistant_message_id": str(assistant_message.id),
                "document_ids": [str(document_id) for document_id in document_ids],
                "confidence_score": confidence_score,
                "confidence_category": confidence_category,
                "not_found": not_found,
                "citation_count": len(citations),
                "latencies_ms": latencies_ms,
                "answer_latency_ms": answer_latency_ms,
                "retrieval_count": len(retrieved_chunks),
                "selected_count": len(selected_chunks),
                "rerank_applied": payload.rerank,
                "embedding_model": embedding_model,
                "llm_model": llm_model,
            },
        )
        await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="chat.query.completed",
            resource_type="chat_session",
            resource_id=chat_session.id,
            request_id=request_id,
            metadata={
                "assistant_message_id": str(assistant_message.id),
                "not_found": not_found,
                "confidence_category": confidence_category,
                "citation_count": len(citations),
                "retrieval_count": len(retrieved_chunks),
                "selected_count": len(selected_chunks),
                "rerank_applied": payload.rerank,
                "status_code": status.HTTP_200_OK,
            },
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
        confidence_category=confidence_category,
        retrieval_count=len(retrieved_chunks),
        selected_count=len(selected_chunks),
    )
    return ChatQueryResponse(
        chat_session_id=str(chat_session.id),
        message_id=str(assistant_message.id),
        answer=answer,
        confidence_score=confidence_score,
        confidence_category=confidence_category,
        confidence_explanation=ChatConfidenceExplanationResponse(
            top_similarity=confidence_explanation.top_similarity,
            average_similarity=confidence_explanation.average_similarity,
            top_rerank_score=confidence_explanation.top_rerank_score,
            citation_support_score=confidence_explanation.citation_support_score,
            citation_validation_score=confidence_explanation.citation_validation_score,
            citation_coverage_score=confidence_explanation.citation_coverage_score,
            retrieval_agreement_score=confidence_explanation.retrieval_agreement_score,
            raw_score=confidence_explanation.raw_score,
            citation_validation_multiplier=confidence_explanation.citation_validation_multiplier,
            not_found_penalty_multiplier=confidence_explanation.not_found_penalty_multiplier,
            no_context=confidence_explanation.no_context,
            not_found_signal=confidence_explanation.not_found_signal,
            weights=confidence_explanation.weights,
            thresholds=confidence_explanation.thresholds,
        ),
        not_found=not_found,
        citations=[] if not_found else citations,
        citation_validation_failed=citation_validation_failed,
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


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_chat_session(
    session_id: str,
    payload: UpdateChatSessionRequest,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    chat_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if chat_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    title = payload.title.strip() if payload.title is not None else None
    chat_session = await chat_repository.update_chat_session_title(
        db_session,
        chat_session=chat_session,
        title=title,
    )
    await db_session.commit()
    await db_session.refresh(chat_session)

    message_counts = await chat_repository.count_messages_by_session_ids(
        db_session,
        session_ids=[chat_session.id],
    )

    log_query_event(
        event="chat.session.updated",
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


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
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
) -> None:
    user_id, organization_id = _principal_user_and_org(principal)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    deleted = await chat_repository.delete_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    await db_session.commit()

    log_query_event(
        event="chat.session.deleted",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_204_NO_CONTENT,
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


# ---------------------------------------------------------------------------
# Share endpoints
# ---------------------------------------------------------------------------


def _to_share_response(share: "ChatShare") -> ChatShareResponse:  # type: ignore[name-defined]  # noqa: F821
    from app.models.chat_share import ChatShare as _ChatShare  # noqa: F401

    return ChatShareResponse(
        share_id=str(share.id),
        session_id=str(share.chat_session_id),
        token=share.token,
        created_at=share.created_at,
        expires_at=share.expires_at,
        is_revoked=share.is_revoked,
        shared_by_user_id=str(share.shared_by_user_id),
    )


@router.post(
    "/sessions/{session_id}/shares",
    response_model=ChatShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_share(
    session_id: str,
    payload: CreateChatShareRequest,
    request: Request,
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
) -> ChatShareResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    chat_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if chat_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    active_count = await share_repository.count_active_chat_shares(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if active_count >= _MAX_ACTIVE_SHARES_PER_SESSION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum of {_MAX_ACTIVE_SHARES_PER_SESSION} active share links per session reached.",
        )

    expires_at: datetime | None = None
    if payload.expires_in_hours is not None:
        expires_at = datetime.now(tz=UTC) + timedelta(hours=payload.expires_in_hours)

    token = secrets.token_urlsafe(32)
    share = await share_repository.create_chat_share(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        shared_by_user_id=user_id,
        token=token,
        expires_at=expires_at,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.session.shared",
        resource_type="chat_session",
        resource_id=chat_session_id,
        request_id=request_id,
        metadata={
            "share_id": str(share.id),
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    await db_session.commit()
    await db_session.refresh(share)

    log_query_event(
        event="chat.session.shared",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_201_CREATED,
    )
    return _to_share_response(share)


@router.get("/sessions/{session_id}/shares", response_model=ChatShareListResponse)
async def list_chat_shares(
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
) -> ChatShareListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    chat_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if chat_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    shares = await share_repository.list_active_chat_shares(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    items = [_to_share_response(s) for s in shares]
    return ChatShareListResponse(items=items, total=len(items))


@router.delete(
    "/sessions/{session_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_chat_share(
    session_id: str,
    share_id: str,
    request: Request,
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
) -> None:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)
    try:
        chat_session_id = UUID(session_id)
        share_uuid = UUID(share_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Share not found"
        ) from exc

    revoked = await share_repository.revoke_chat_share(
        db_session,
        share_id=share_uuid,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.session.share.revoked",
        resource_type="chat_session",
        resource_id=chat_session_id,
        request_id=request_id,
        metadata={"share_id": share_id},
    )
    await db_session.commit()

    log_query_event(
        event="chat.session.share.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=session_id,
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.get("/shared/{token}", response_model=SharedSessionResponse)
async def get_shared_session(
    token: str,
    request: Request,
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
) -> SharedSessionResponse:
    _, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)

    share = await share_repository.get_chat_share_by_token(
        db_session,
        token=token,
        organization_id=organization_id,
    )
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found, expired, or revoked.",
        )

    from sqlalchemy import select as _select

    from app.models.chat import ChatSession as _ChatSession

    result = await db_session.execute(
        _select(_ChatSession).where(_ChatSession.id == share.chat_session_id)
    )
    chat_session = result.scalar_one_or_none()
    if chat_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found, expired, or revoked.",
        )

    messages_orm = await chat_repository.list_chat_messages(
        db_session,
        chat_session_id=chat_session.id,
        limit=500,
        offset=0,
    )
    total_messages = await chat_repository.count_chat_messages(
        db_session,
        chat_session_id=chat_session.id,
    )

    items: list[ChatSessionMessageResponse] = []
    for message in messages_orm:
        message_citations: list[ChatCitationResponse] = []
        if message.role == ChatRole.assistant.value:
            citation_rows = await chat_repository.list_citations_for_message_with_filename(
                db_session,
                chat_message_id=message.id,
            )
            message_citations = [
                ChatCitationResponse(
                    document_id=str(citation.document_id),
                    chunk_id=str(citation.chunk_id),
                    filename=filename,
                    page_number=citation.page_number,
                    score=citation.rerank_score
                    if citation.rerank_score is not None
                    else citation.similarity_score,
                    similarity_score=citation.similarity_score,
                    rerank_score=citation.rerank_score,
                    rerank_rank=None,
                    text_snippet=citation.text_snippet,
                    start_offset=citation.start_offset,
                    end_offset=citation.end_offset,
                )
                for citation, filename in citation_rows
            ]

        items.append(
            ChatSessionMessageResponse(
                message_id=str(message.id),
                role=message.role,
                content=message.content,
                confidence_score=message.confidence_score,
                confidence_category=_confidence_category_from_score(message.confidence_score),
                citations=message_citations,
                created_at=message.created_at,
            )
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=principal.user_id,
        action="chat.session.share.viewed",
        resource_type="chat_session",
        resource_id=chat_session.id,
        request_id=request_id,
        metadata={"share_id": str(share.id), "share_owner_user_id": str(share.shared_by_user_id)},
    )
    await db_session.commit()

    log_query_event(
        event="chat.session.share.viewed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(chat_session.id),
        status_code=status.HTTP_200_OK,
    )
    return SharedSessionResponse(
        session_id=str(chat_session.id),
        title=chat_session.title,
        shared_at=share.created_at,
        messages=items,
        total_messages=total_messages,
    )


# ---------------------------------------------------------------------------
# Feedback endpoints
# ---------------------------------------------------------------------------


def _to_feedback_response(fb: "MessageFeedback") -> MessageFeedbackResponse:  # type: ignore[name-defined]  # noqa: F821
    from app.models.message_feedback import MessageFeedback as _MessageFeedback  # noqa: F401

    return MessageFeedbackResponse(
        feedback_id=str(fb.id),
        message_id=str(fb.message_id),
        user_id=str(fb.user_id),
        rating=fb.rating,  # type: ignore[arg-type]
        reason=fb.reason,  # type: ignore[arg-type]
        comment=fb.comment,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
    )


async def _get_assistant_message_for_org(
    db_session: AsyncSession,
    *,
    message_id: UUID,
    organization_id: UUID,
) -> "ChatMessage":  # type: ignore[name-defined]  # noqa: F821
    from sqlalchemy import select as _select

    from app.models.chat import ChatMessage as _ChatMessage
    from app.models.chat import ChatSession as _ChatSession

    result = await db_session.execute(
        _select(_ChatMessage)
        .join(_ChatSession, _ChatMessage.chat_session_id == _ChatSession.id)
        .where(
            _ChatMessage.id == message_id,
            _ChatMessage.role == "assistant",
            _ChatSession.organization_id == organization_id,
        )
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return message


@router.put(
    "/messages/{message_id}/feedback",
    response_model=MessageFeedbackResponse,
)
async def submit_message_feedback(
    message_id: str,
    payload: SubmitFeedbackRequest,
    request: Request,
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
) -> MessageFeedbackResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)
    try:
        msg_id = UUID(message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc

    await _get_assistant_message_for_org(
        db_session, message_id=msg_id, organization_id=organization_id
    )

    feedback = await feedback_repository.upsert_feedback(
        db_session,
        message_id=msg_id,
        user_id=user_id,
        organization_id=organization_id,
        rating=payload.rating,
        reason=payload.reason,
        comment=payload.comment,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.message.feedback.submitted",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={"rating": payload.rating, "reason": payload.reason},
    )
    await db_session.commit()
    await db_session.refresh(feedback)
    return _to_feedback_response(feedback)


@router.delete("/messages/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_feedback(
    message_id: str,
    request: Request,
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
) -> None:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)
    try:
        msg_id = UUID(message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc

    deleted = await feedback_repository.delete_feedback(
        db_session,
        message_id=msg_id,
        user_id=user_id,
        organization_id=organization_id,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.message.feedback.deleted",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={},
    )
    await db_session.commit()


@router.get(
    "/sessions/{session_id}/feedback",
    response_model=SessionFeedbackListResponse,
)
async def list_session_feedback(
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
) -> SessionFeedbackListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    try:
        chat_session_id = UUID(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found"
        ) from exc

    chat_session = await chat_repository.get_chat_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if chat_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    items = await feedback_repository.list_feedback_for_session(
        db_session,
        chat_session_id=chat_session_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    return SessionFeedbackListResponse(
        items=[_to_feedback_response(fb) for fb in items],
        total=len(items),
    )
