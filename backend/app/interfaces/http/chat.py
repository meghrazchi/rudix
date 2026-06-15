import asyncio
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.auth.passwords import (
    PasswordHashConfig,
    build_password_hasher,
    hash_password,
    verify_password,
)
from app.clients import qdrant_client as qdrant_module
from app.clients import redis_client as redis_module
from app.core.config import settings
from app.core.langfuse_tracer import ChatTraceMetadata, trace_chat_query
from app.core.logging import log_query_event
from app.core.safety_guardrails import PromptInjectionGuard
from app.db.session import SessionLocal, get_db_session
from app.domains.admin.repositories.usage import UsageRepository
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.admin.services.feature_flag_service import FeatureFlagService
from app.domains.ai.profile.schemas import TaskType
from app.domains.ai.profile.service import resolve_task_profile
from app.domains.chat.repositories.answer_share import AnswerShareRepository
from app.domains.chat.repositories.chat import ChatRepository
from app.domains.chat.repositories.feedback import FeedbackRepository
from app.domains.chat.repositories.share import ChatShareRepository
from app.domains.chat.schemas.answer_share import (
    AnswerShareListResponse,
    AnswerShareResponse,
    CreateAnswerShareRequest,
    SharedAnswerCitationResponse,
    SharedAnswerResponse,
)
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
    ChatStatsResponse,
    CreateChatSessionRequest,
    UpdateChatSessionRequest,
)
from app.domains.chat.schemas.chat_ws import ChatWSInboundMessage, ChatWSOutboundEvent
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
from app.domains.chat.services.citation_service import CitationContextChunk, CitationService
from app.domains.chat.services.confidence_service import ConfidenceChunkSignal, ConfidenceService
from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievalResult,
    GraphRetrievalService,
    GraphRetrievedChunk,
)
from app.domains.chat.services.hybrid_retrieval_service import (
    HybridCandidate,
    HybridRetrievalService,
)
from app.domains.chat.services.keyword_retrieval_service import KeywordRetrievalService
from app.domains.chat.services.language_service import detect_language, resolve_answer_language
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
from app.domains.chat.services.rerank_service import (
    RerankCandidate,
    RerankResult,
    RerankService,
    RerankSettings,
)
from app.domains.chat.services.source_scope_service import SourceScopeService
from app.domains.connectors.services.source_provenance import SourceProvenanceService
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.domains.prompt_templates.services.rendering import PromptTemplateValidationError
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig
from app.domains.rag_profiles.services.rag_profile_service import resolve_profile_for_context
from app.models.enums import ChatRole, OrganizationRole, PromptTemplateKey
from app.models.prompt_template import PromptTemplateVersion
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.rate_limit.dependencies import _build_key, _rate_limit_disabled, _scope_limit

router = APIRouter(prefix="/chat", tags=["chat"])
# Separate router for WebSocket — must NOT be under protected_router because
# the browser WebSocket API cannot send an Authorization header during the HTTP
# upgrade, so FastAPI's router-level get_current_principal dependency would fail.
ws_router = APIRouter(prefix="/chat", tags=["chat"])
chat_repository = ChatRepository()
share_repository = ChatShareRepository()
answer_share_repository = AnswerShareRepository()
feedback_repository = FeedbackRepository()
usage_repository = UsageRepository()
audit_log_service = AuditLogService()

_MAX_ACTIVE_SHARES_PER_SESSION = 10
_query_retrieval_service = QueryRetrievalService()
_keyword_retrieval_service = KeywordRetrievalService()
_hybrid_retrieval_service = HybridRetrievalService()
_source_scope_service = SourceScopeService()
_rerank_service = RerankService()
_prompt_service = PromptService()
_prompt_template_service = PromptTemplateService()
_citation_service = CitationService()
_source_provenance_service = SourceProvenanceService()
_confidence_service = ConfidenceService()
_graph_retrieval_service = GraphRetrievalService()
_feature_flag_service = FeatureFlagService()
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
    original_rank: int | None = None
    rerank_score: float | None = None
    rerank_rank: int | None = None
    final_rank: int | None = None
    retrieval_source: str = "vector"
    graph_score: float | None = None
    graph_hops: int = 0
    keyword_score: float | None = None
    hybrid_score: float | None = None


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


def _hybrid_to_retrieved_chunk(candidate: HybridCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
        retrieval_source=candidate.retrieval_source,
        keyword_score=candidate.keyword_score,
        hybrid_score=candidate.hybrid_score,
    )


def _to_graph_retrieved_chunk(candidate: GraphRetrievedChunk) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
        retrieval_source="graph",
        graph_score=candidate.graph_score,
        graph_hops=candidate.graph_hops,
    )


def _merge_retrieved_chunks(
    vector_chunks: list[RetrievedChunk],
    graph_chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    insertion_order: list[str] = []

    def _merge_graph_hops(existing_hops: int, new_hops: int) -> int:
        if existing_hops == 0:
            return new_hops
        if new_hops == 0:
            return existing_hops
        return min(existing_hops, new_hops)

    def _upsert(chunk: RetrievedChunk) -> None:
        key = str(chunk.chunk_id)
        existing = merged.get(key)
        if existing is None:
            merged[key] = chunk
            insertion_order.append(key)
            return

        merged[key] = RetrievedChunk(
            document_id=existing.document_id,
            chunk_id=existing.chunk_id,
            filename=existing.filename or chunk.filename,
            page_number=(
                existing.page_number if existing.page_number is not None else chunk.page_number
            ),
            text=existing.text if len(existing.text) >= len(chunk.text) else chunk.text,
            similarity_score=max(existing.similarity_score, chunk.similarity_score),
            rerank_score=existing.rerank_score,
            rerank_rank=existing.rerank_rank,
            retrieval_source="merged",
            graph_score=max(
                existing.graph_score or 0.0,
                chunk.graph_score or 0.0,
            )
            or None,
            graph_hops=_merge_graph_hops(existing.graph_hops, chunk.graph_hops),
        )

    for chunk in vector_chunks:
        _upsert(chunk)
    for chunk in graph_chunks:
        _upsert(chunk)

    return [merged[key] for key in insertion_order]


def _with_original_ranks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    ranked_chunks: list[RetrievedChunk] = []
    for index, chunk in enumerate(chunks, start=1):
        ranked_chunks.append(
            RetrievedChunk(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=index,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
                retrieval_source=chunk.retrieval_source,
                graph_score=chunk.graph_score,
                graph_hops=chunk.graph_hops,
                keyword_score=chunk.keyword_score,
                hybrid_score=chunk.hybrid_score,
            )
        )
    return ranked_chunks


def _with_provenance(
    citation: ChatCitationResponse,
    provenance: Any | None,
) -> ChatCitationResponse:
    if provenance is None:
        return citation

    return ChatCitationResponse(
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=provenance.provider_key,
        source_provider_label=provenance.provider_label,
        source_title=provenance.source_title,
        source_key=provenance.source_key,
        source_section=provenance.source_section,
        source_deep_link=provenance.source_deep_link,
        source_last_synced_at=provenance.source_last_synced_at,
        source_trust_status=cast(Any, provenance.source_trust_status),
        source_acl_snapshot=provenance.source_acl_snapshot,
    )


async def _rerank_chunks(
    *,
    query: str,
    chunks: list[RetrievedChunk],
    enabled: bool,
    final_top_k: int,
    settings_override: RerankSettings | None = None,
) -> tuple[list[RetrievedChunk], RerankResult]:
    if final_top_k < 1 or not chunks:
        empty_result = await _rerank_service.rerank(
            query=query,
            candidates=[],
            enabled=enabled,
            final_top_k=final_top_k,
            settings_override=settings_override,
        )
        return [], empty_result

    chunk_by_key = {str(chunk.chunk_id): chunk for chunk in chunks}
    rerank_inputs = [
        RerankCandidate(
            key=str(chunk.chunk_id),
            text=chunk.text,
            similarity_score=chunk.similarity_score,
            original_rank=chunk.original_rank,
        )
        for chunk in chunks
    ]

    rerank_result: RerankResult = await _rerank_service.rerank(
        query=query,
        candidates=rerank_inputs,
        enabled=enabled,
        final_top_k=final_top_k,
        settings_override=settings_override,
    )

    selected_chunks: list[RetrievedChunk] = []
    for reranked in rerank_result.candidates:
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
                original_rank=reranked.original_rank,
                rerank_score=reranked.rerank_score,
                rerank_rank=reranked.rerank_rank,
                final_rank=reranked.final_rank,
                retrieval_source=source_chunk.retrieval_source,
                graph_score=source_chunk.graph_score,
                graph_hops=source_chunk.graph_hops,
                keyword_score=source_chunk.keyword_score,
                hybrid_score=source_chunk.hybrid_score,
            )
        )
    return selected_chunks, rerank_result


def _build_prompt(
    *,
    question: str,
    chunks: list[RetrievedChunk],
    answer_language: str | None = None,
    template: str | None = None,
) -> str:
    return _prompt_service.build_prompt(
        question=question,
        not_found_answer=_NOT_FOUND_ANSWER,
        answer_language=answer_language,
        template=template,
        chunks=[
            PromptContextChunk(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=chunk.original_rank,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
            )
            for chunk in chunks
        ],
    )


async def _resolve_answer_prompt_version(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> PromptTemplateVersion:
    try:
        return await _prompt_template_service.resolve_active_version(
            db_session,
            organization_id=organization_id,
            template_key=PromptTemplateKey.answer_generation.value,
        )
    except PromptTemplateValidationError as exc:
        raise _safe_http_error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="prompt_template_unavailable",
            message="Answer prompt template is unavailable",
        ) from exc


def _build_rerank_settings(config: dict | None) -> RerankSettings:
    profile_config = RagProfileConfig.model_validate(config or {})
    return RerankSettings(
        enabled=profile_config.rerank_enabled if config is not None else True,
        provider_key=profile_config.rerank_provider,
        model_name=profile_config.rerank_model,
        timeout_seconds=profile_config.rerank_timeout_seconds,
        batch_size=profile_config.rerank_batch_size,
        max_input_candidates=profile_config.rerank_input_max_candidates,
        max_candidate_chars=profile_config.rerank_max_candidate_chars,
        fallback_behavior=profile_config.rerank_fallback_behavior,
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


async def _resolve_graph_rag_enabled(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> bool:
    try:
        return await _feature_flag_service.is_enabled(
            db_session,
            organization_id=organization_id,
            flag_name="graph_rag",
        )
    except Exception as exc:
        log_query_event(
            event="query.graph.feature_flag_fallback",
            organization_id=str(organization_id),
            error=exc.__class__.__name__,
            detail=str(exc),
            enabled=settings.feature_enable_graph_rag,
        )
        return settings.feature_enable_graph_rag


async def _augment_retrieval_with_graph_context(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    question: str,
    vector_chunks: list[RetrievedChunk],
    allowed_document_ids: list[UUID] | None,
    graph_enabled: bool,
) -> tuple[list[RetrievedChunk], GraphRetrievalResult]:
    if not graph_enabled:
        return vector_chunks, GraphRetrievalResult(
            graph_context_enabled=False,
            graph_context_used=False,
            graph_context_reason="disabled",
        )

    graph_result = await _graph_retrieval_service.expand(
        session=db_session,
        organization_id=organization_id,
        question=question,
        allowed_document_ids=allowed_document_ids,
        graph_enabled=True,
    )
    if not graph_result.chunks:
        return vector_chunks, graph_result

    graph_chunks = [_to_graph_retrieved_chunk(chunk) for chunk in graph_result.chunks]
    return _merge_retrieved_chunks(vector_chunks, graph_chunks), graph_result


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


@router.get("/stats", response_model=ChatStatsResponse)
async def get_chat_stats(
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
) -> ChatStatsResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    total_sessions = await chat_repository.count_chat_sessions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
    )
    questions_asked = await chat_repository.count_user_questions(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
    )
    return ChatStatsResponse(
        questions_asked=questions_asked,
        total_sessions=total_sessions,
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
            provenance_by_document_id = (
                await _source_provenance_service.load_citation_details_for_documents(
                    db_session,
                    organization_id=organization_id,
                    document_ids=[citation.document_id for citation, _ in citation_rows],
                )
            )
            message_citations = [
                _with_provenance(
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
                    ),
                    provenance_by_document_id.get(citation.document_id),
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
    user_roles = list(principal.roles or [])
    try:
        explicit_document_ids = await ensure_document_ids_access(
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

    source_scope_result = await _source_scope_service.resolve_document_ids(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=user_roles,
        source_scope=payload.source_scope,
        explicit_document_ids=explicit_document_ids,
    )
    document_ids = source_scope_result.document_ids

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

    answer_prompt_version: PromptTemplateVersion | None = None
    answer_prompt_template: str | None = None
    if payload.scope_mode != "none":
        answer_prompt_version = await _resolve_answer_prompt_version(
            db_session,
            organization_id=organization_id,
        )
        answer_prompt_template = answer_prompt_version.content

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
    rag_profile, _ = await resolve_profile_for_context(
        db_session,
        organization_id=organization_id,
        collection_id=None,
    )
    rerank_settings = _build_rerank_settings(
        dict(rag_profile.config) if rag_profile is not None else None
    )

    retrieved_chunks: list[RetrievedChunk] = []
    selected_chunks: list[RetrievedChunk] = []
    embedding_prompt_tokens = 0
    hybrid_retrieval_enabled = False
    hybrid_vector_hit_count = 0
    hybrid_keyword_hit_count = 0
    hybrid_exact_match_tokens: list[str] = []
    llm_prompt_tokens = 0
    llm_completion_tokens = 0
    llm_model: str | None = None
    llm_provider: str | None = None
    llm_fallback_used = False
    llm_fallback_from: str | None = None
    llm_fallback_to: str | None = None
    llm_fallback_reason: str | None = None
    llm_retry_count: int | None = None
    llm_cost_usd = None
    llm_latency_ms = 0
    answer = _NOT_FOUND_ANSWER
    citations: list[ChatCitationResponse] = []
    not_found = injection_check.blocked
    citation_validation_failed = False
    graph_context_result = GraphRetrievalResult()
    rerank_result: RerankResult | None = None

    # Resolve the effective model profile for this organisation (F223).
    chat_profile = await resolve_task_profile(
        db_session,
        organization_id=organization_id,
        task_type=TaskType.chat,
    )

    # Language detection and answer language resolution (F231).
    detected_language: str | None = None
    answer_language_used: str | None = None
    if settings.feature_enable_language_aware_rag and not injection_check.blocked:
        detected_language = detect_language(payload.question)
        answer_language_used = resolve_answer_language(
            mode=payload.answer_language,
            detected_language=detected_language,
            workspace_default=settings.answer_language_workspace_default,
        )
        log_query_event(
            event="query.language.detected",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            detected_language=detected_language,
            answer_language_mode=payload.answer_language,
            answer_language_used=answer_language_used,
        )

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
        prompt = _prompt_service.build_general_prompt(
            question=payload.question,
            answer_language=answer_language_used,
        )
        try:
            llm_result = await _llm_service.generate_answer(
                prompt=prompt,
                resolved_profile=chat_profile,
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
        llm_provider = llm_result.provider_key
        llm_fallback_used = llm_result.fallback_used
        llm_fallback_from = llm_result.fallback_from
        llm_fallback_to = llm_result.fallback_to
        llm_fallback_reason = llm_result.fallback_reason
        llm_retry_count = llm_result.retry_count
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
        rerank_applied = bool(payload.rerank and rerank_settings.enabled)
        rerank_input_limit = rerank_settings.max_input_candidates or settings.rerank_default_input_candidates
        retrieval_top_k = max(final_top_k, rerank_input_limit if rerank_applied else final_top_k)

        embed_started = perf_counter()
        try:
            query_vector, embedding_prompt_tokens = await _query_retrieval_service.embed_query(
                question=payload.question,
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

            if settings.feature_enable_hybrid_retrieval:
                kw_result = await _keyword_retrieval_service.search_chunks(
                    session=db_session,
                    query=payload.question,
                    organization_id=organization_id,
                    document_ids=document_ids,
                    top_k=retrieval_top_k,
                    exact_match_boost=settings.hybrid_retrieval_exact_match_boost,
                )
                hybrid_result = _hybrid_retrieval_service.merge(
                    vector_candidates=retrieved_candidates,
                    keyword_candidates=kw_result.candidates,
                    exact_match_tokens=kw_result.exact_match_tokens,
                    vector_weight=settings.hybrid_retrieval_vector_weight,
                    rrf_k=settings.hybrid_retrieval_rrf_k,
                    exact_match_boost=settings.hybrid_retrieval_exact_match_boost,
                )
                retrieved_chunks = [
                    _hybrid_to_retrieved_chunk(c) for c in hybrid_result.candidates
                ]
                hybrid_retrieval_enabled = True
                hybrid_vector_hit_count = hybrid_result.vector_hit_count
                hybrid_keyword_hit_count = hybrid_result.keyword_hit_count
                hybrid_exact_match_tokens = hybrid_result.exact_match_tokens
            else:
                retrieved_chunks = [
                    _to_retrieved_chunk(candidate) for candidate in retrieved_candidates
                ]

            retrieved_chunks = await _source_provenance_service.filter_active_chunks(
                db_session,
                organization_id=organization_id,
                chunks=retrieved_chunks,
            )
            graph_enabled = await _resolve_graph_rag_enabled(
                db_session, organization_id=organization_id
            )
            retrieved_chunks, graph_context_result = await _augment_retrieval_with_graph_context(
                db_session,
                organization_id=organization_id,
                question=payload.question,
                vector_chunks=retrieved_chunks,
                allowed_document_ids=document_ids,
                graph_enabled=graph_enabled,
            )
            retrieved_chunks = _with_original_ranks(retrieved_chunks)
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
        selected_chunks, rerank_result = await _rerank_chunks(
            query=payload.question,
            chunks=retrieved_chunks,
            enabled=rerank_applied,
            final_top_k=final_top_k,
            settings_override=rerank_settings,
        )
        latencies_ms["rerank"] = int((perf_counter() - rerank_started) * 1000)

        confidence_signals = _to_confidence_signals(
            chunks=selected_chunks, rerank_applied=rerank_applied
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
            _build_prompt(
                question=payload.question,
                chunks=selected_chunks,
                answer_language=answer_language_used,
                template=answer_prompt_template,
            )
            if not not_found
            else ""
        )
        latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

        if not not_found:
            try:
                llm_result = await _llm_service.generate_answer(
                    prompt=prompt,
                    resolved_profile=chat_profile,
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
            llm_provider = llm_result.provider_key
            llm_fallback_used = llm_result.fallback_used
            llm_fallback_from = llm_result.fallback_from
            llm_fallback_to = llm_result.fallback_to
            llm_fallback_reason = llm_result.fallback_reason
            llm_retry_count = llm_result.retry_count
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
                            original_rank=chunk.original_rank,
                            rerank_score=chunk.rerank_score,
                            rerank_rank=chunk.rerank_rank,
                            final_rank=chunk.final_rank,
                        )
                        for chunk in selected_chunks
                    ],
                    model_citations=llm_result.citations,
                )
                provenance_by_chunk_id = await _source_provenance_service.load_citation_details(
                    db_session,
                    organization_id=organization_id,
                    chunk_ids=[UUID(citation.chunk_id) for citation in citation_result.citations],
                )
                citations = [
                    _with_provenance(citation, provenance_by_chunk_id.get(UUID(citation.chunk_id)))
                    for citation in citation_result.citations
                ]
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
    rerank_diagnostics = rerank_result.diagnostics if rerank_result is not None else None

    persist_started = perf_counter()
    try:
        persisted_document_ids = (
            [str(document_id) for document_id in document_ids] if document_ids is not None else []
        )
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
            prompt_template_version_id=answer_prompt_version.id
            if answer_prompt_version is not None
            else None,
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
                rerank_score=citation.rerank_score if rerank_applied else None,
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
            provider_key=llm_provider,
            task_type="chat",
            retry_count=llm_retry_count,
            fallback_used=llm_fallback_used,
            request_id=request_id,
            metadata={
                "chat_session_id": str(chat_session.id),
                "assistant_message_id": str(assistant_message.id),
                "document_ids": persisted_document_ids,
                "confidence_score": confidence_score,
                "confidence_category": confidence_category,
                "not_found": not_found,
                "citation_count": len(citations),
                "latencies_ms": latencies_ms,
                "answer_latency_ms": answer_latency_ms,
                "retrieval_count": len(retrieved_chunks),
                "selected_count": len(selected_chunks),
                "graph_context_enabled": graph_context_result.graph_context_enabled,
                "graph_context_used": graph_context_result.graph_context_used,
                "graph_context_unavailable": graph_context_result.graph_context_unavailable,
                "graph_context_reason": graph_context_result.graph_context_reason,
                "graph_seed_entity_count": graph_context_result.graph_seed_entity_count,
                "graph_related_entity_count": graph_context_result.graph_related_entity_count,
                "graph_chunk_count": graph_context_result.graph_chunk_count,
                "graph_max_hops_used": graph_context_result.graph_max_hops_used,
                "graph_relation_types_used": list(graph_context_result.graph_relation_types_used),
                "rerank_applied": rerank_applied,
                "rerank_enabled": rerank_settings.enabled,
                "rerank_provider": rerank_diagnostics.provider_key if rerank_diagnostics else None,
                "rerank_model": rerank_diagnostics.model_name if rerank_diagnostics else None,
                "rerank_fallback_used": rerank_diagnostics.fallback_used if rerank_diagnostics else False,
                "rerank_fallback_reason": rerank_diagnostics.fallback_reason if rerank_diagnostics else None,
                "rerank_input_count": rerank_diagnostics.requested_count if rerank_diagnostics else 0,
                "rerank_batch_count": rerank_diagnostics.batch_count if rerank_diagnostics else 0,
                "rerank_prompt_tokens": rerank_diagnostics.prompt_tokens if rerank_diagnostics else 0,
                "rerank_completion_tokens": rerank_diagnostics.completion_tokens if rerank_diagnostics else 0,
                "rerank_total_tokens": rerank_diagnostics.total_tokens if rerank_diagnostics else 0,
                "rerank_cost_usd": float(rerank_diagnostics.approximate_cost_usd) if rerank_diagnostics else None,
                "embedding_model": embedding_model,
                "llm_model": llm_model,
                "llm_provider": llm_provider,
                "fallback_used": llm_fallback_used,
                "fallback_from": llm_fallback_from,
                "fallback_to": llm_fallback_to,
                "fallback_reason": llm_fallback_reason,
                "prompt_template": {
                    "key": PromptTemplateKey.answer_generation.value,
                    "version_number": answer_prompt_version.version_number,
                    "version_id": str(answer_prompt_version.id),
                }
                if answer_prompt_version is not None
                else None,
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
                "graph_context_used": graph_context_result.graph_context_used,
                "graph_context_reason": graph_context_result.graph_context_reason,
                "rerank_applied": rerank_applied,
                "rerank_enabled": rerank_settings.enabled,
                "rerank_provider": rerank_diagnostics.provider_key if rerank_diagnostics else None,
                "rerank_model": rerank_diagnostics.model_name if rerank_diagnostics else None,
                "prompt_template_key": PromptTemplateKey.answer_generation.value
                if answer_prompt_version is not None
                else None,
                "prompt_template_version": answer_prompt_version.version_number
                if answer_prompt_version is not None
                else None,
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

    trace_chat_query(
        ChatTraceMetadata(
            request_id=request_id,
            organization_id=str(organization_id),
            user_id=str(user_id) if user_id is not None else "",
            session_id=str(chat_session.id),
            message_id=str(assistant_message.id),
            question=payload.question,
            answer=answer,
            scope_mode=payload.scope_mode,
            source_scope_label=source_scope_result.label,
            feature_area="chat",
            retrieved_count=len(retrieved_chunks),
            selected_count=len(selected_chunks),
            rerank_applied=rerank_applied,
            rerank_enabled=rerank_settings.enabled,
            rerank_provider=rerank_diagnostics.provider_key if rerank_diagnostics else None,
            rerank_model=rerank_diagnostics.model_name if rerank_diagnostics else None,
            rerank_fallback_used=rerank_diagnostics.fallback_used if rerank_diagnostics else False,
            rerank_fallback_reason=rerank_diagnostics.fallback_reason if rerank_diagnostics else None,
            rerank_input_count=rerank_diagnostics.requested_count if rerank_diagnostics else 0,
            rerank_batch_count=rerank_diagnostics.batch_count if rerank_diagnostics else 0,
            rerank_prompt_tokens=rerank_diagnostics.prompt_tokens if rerank_diagnostics else 0,
            rerank_completion_tokens=rerank_diagnostics.completion_tokens if rerank_diagnostics else 0,
            rerank_total_tokens=rerank_diagnostics.total_tokens if rerank_diagnostics else 0,
            rerank_cost_usd=rerank_diagnostics.approximate_cost_usd if rerank_diagnostics else None,
            cited_count=len(citations),
            not_found=not_found,
            citation_validation_failed=citation_validation_failed,
            confidence_score=confidence_score,
            confidence_category=confidence_category,
            llm_model=llm_model,
            llm_provider=llm_provider,
            embedding_model=embedding_model,
            fallback_used=llm_fallback_used,
            fallback_reason=llm_fallback_reason,
            embedding_prompt_tokens=embedding_prompt_tokens,
            llm_prompt_tokens=llm_prompt_tokens,
            llm_completion_tokens=llm_completion_tokens,
            llm_total_tokens=embedding_prompt_tokens + llm_prompt_tokens + llm_completion_tokens,
            estimated_cost_usd=llm_cost_usd,
            latencies_ms=dict(latencies_ms),
            answer_latency_ms=answer_latency_ms,
            detected_language=detected_language,
            answer_language_used=answer_language_used,
            prompt_template_key=PromptTemplateKey.answer_generation.value
            if answer_prompt_version is not None
            else None,
            prompt_template_version=answer_prompt_version.version_number
            if answer_prompt_version is not None
            else None,
        )
    )

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
        graph_context_used=graph_context_result.graph_context_used,
        graph_context_reason=graph_context_result.graph_context_reason,
        source_scope=source_scope_result.label,
        detected_language=detected_language,
        answer_language_mode=payload.answer_language,
        answer_language_used=answer_language_used,
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
            rerank_applied=rerank_applied,
            rerank_enabled=rerank_settings.enabled,
            rerank_provider=rerank_diagnostics.provider_key if rerank_diagnostics else None,
            rerank_model=rerank_diagnostics.model_name if rerank_diagnostics else None,
            rerank_fallback_used=rerank_diagnostics.fallback_used if rerank_diagnostics else False,
            rerank_fallback_reason=rerank_diagnostics.fallback_reason if rerank_diagnostics else None,
            rerank_input_count=rerank_diagnostics.requested_count if rerank_diagnostics else 0,
            rerank_batch_count=rerank_diagnostics.batch_count if rerank_diagnostics else 0,
            rerank_prompt_tokens=rerank_diagnostics.prompt_tokens if rerank_diagnostics else 0,
            rerank_completion_tokens=rerank_diagnostics.completion_tokens if rerank_diagnostics else 0,
            rerank_total_tokens=rerank_diagnostics.total_tokens if rerank_diagnostics else 0,
            rerank_cost_usd=float(rerank_diagnostics.approximate_cost_usd)
            if rerank_diagnostics
            else None,
            source_scope=source_scope_result.label,
            graph_context_enabled=graph_context_result.graph_context_enabled,
            graph_context_used=graph_context_result.graph_context_used,
            graph_context_unavailable=graph_context_result.graph_context_unavailable,
            graph_context_reason=graph_context_result.graph_context_reason,
            graph_seed_entity_count=graph_context_result.graph_seed_entity_count,
            graph_related_entity_count=graph_context_result.graph_related_entity_count,
            graph_chunk_count=graph_context_result.graph_chunk_count,
            graph_max_hops_used=graph_context_result.graph_max_hops_used,
            graph_relation_types_used=list(graph_context_result.graph_relation_types_used),
            embedding_model=embedding_model,
            llm_model=llm_model,
            llm_provider=llm_provider,
            fallback_used=llm_fallback_used,
            fallback_from=llm_fallback_from,
            fallback_to=llm_fallback_to,
            fallback_reason=llm_fallback_reason,
            detected_language=detected_language,
            answer_language_used=answer_language_used,
            prompt_template_key=PromptTemplateKey.answer_generation.value
            if answer_prompt_version is not None
            else None,
            prompt_template_version=answer_prompt_version.version_number
            if answer_prompt_version is not None
            else None,
            prompt_template_version_id=str(answer_prompt_version.id)
            if answer_prompt_version is not None
            else None,
            hybrid_retrieval_enabled=hybrid_retrieval_enabled,
            hybrid_vector_hit_count=hybrid_vector_hit_count,
            hybrid_keyword_hit_count=hybrid_keyword_hit_count,
            hybrid_exact_match_tokens=hybrid_exact_match_tokens,
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


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket chat transport (F277)
# ──────────────────────────────────────────────────────────────────────────────

# Per-user active connection counter (in-process; replace with Redis for multi-instance).
_ws_connection_counts: dict[str, int] = {}
_ws_connection_lock = asyncio.Lock()


async def _ws_send(websocket: WebSocket, event: ChatWSOutboundEvent) -> None:
    try:
        await websocket.send_text(event.to_json())
    except Exception:
        pass


async def _ws_rate_limit_chat(principal: AuthenticatedPrincipal) -> bool:
    """Returns True if the request is allowed, False if rate-limited."""
    if _rate_limit_disabled():
        return True
    from math import floor
    from time import time

    limit = _scope_limit(RateLimitScope.chat)
    window_seconds = settings.rate_limit_window_seconds
    window_bucket = floor(time() / window_seconds)
    organization_id = principal.organization_id or "none"
    key = _build_key(
        scope=RateLimitScope.chat,
        endpoint="/chat/ws",
        user_id=principal.user_id,
        organization_id=organization_id,
        window=window_bucket,
    )
    redis = redis_module.redis_client
    if redis is None:
        return True
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
        return int(count) <= limit
    except Exception:
        return True


async def _authenticate_ws_token(
    token: str,
    db_session: AsyncSession,
) -> AuthenticatedPrincipal | None:
    """Authenticate a WebSocket connection from a bearer token string."""
    from app.auth.factory import get_auth_provider

    token = token.strip()
    if not token:
        return None

    if token.startswith("rudix_"):
        # API key path.
        from fastapi import Request as _Request

        scope: dict[str, Any] = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "asgi": {"version": "3.0"},
        }
        try:
            from app.auth.dependencies import _authenticate_api_key as _api_key_auth

            fake_req = _Request(scope)
            return await _api_key_auth(fake_req, token, db_session)
        except Exception:
            return None

    # JWT path - construct a minimal Request with the Authorization header.
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "asgi": {"version": "3.0"},
    }
    try:
        from fastapi import Request as _Request

        fake_req = _Request(scope)
        provider = get_auth_provider()
        return await provider.authenticate(fake_req, db_session)
    except Exception:
        return None


async def _run_ws_chat_pipeline(
    websocket: WebSocket,
    payload: dict[str, Any],
    principal: AuthenticatedPrincipal,
    request_id: str,
    sequence_start: int,
) -> None:
    """Run the full RAG pipeline and stream events over the WebSocket."""
    seq = sequence_start
    conversation_id: str | None = None

    async def send(
        event_type: str,
        extra_payload: dict[str, Any] | None = None,
        message_id: str | None = None,
        safe_error_code: str | None = None,
    ) -> None:
        nonlocal seq
        seq += 1
        evt = ChatWSOutboundEvent(
            event=event_type,  # type: ignore[arg-type]
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=message_id,
            sequence=seq,
            payload=extra_payload,
            safe_error_code=safe_error_code,
        )
        await _ws_send(websocket, evt)

    # Parse and validate the chat query request.
    try:
        query_request = ChatQueryRequest.model_validate(payload)
    except Exception as exc:
        await send("chat.error", safe_error_code="invalid_request")
        log_query_event(
            event="query.failed.ws_parse",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            error=str(exc),
        )
        return

    await send("chat.request.received")

    user_id, organization_id = _principal_user_and_org(principal)
    user_roles = list(principal.roles or [])

    async with SessionLocal() as db_session:
        try:
            # ── Scope validation ──────────────────────────────────────────────
            try:
                explicit_document_ids = await ensure_document_ids_access(
                    document_ids=query_request.document_ids,
                    principal=principal,
                    db_session=db_session,
                )
            except HTTPException:
                await send("chat.error", safe_error_code="document_not_found")
                return

            source_scope_result = await _source_scope_service.resolve_document_ids(
                db_session,
                organization_id=organization_id,
                user_id=user_id,
                user_roles=user_roles,
                source_scope=query_request.source_scope,
                explicit_document_ids=explicit_document_ids,
            )
            document_ids = source_scope_result.document_ids
            await send("chat.scope.validated", {"scope_label": source_scope_result.label})

            # ── Session management ────────────────────────────────────────────
            if query_request.chat_session_id is not None:
                try:
                    chat_session_id = UUID(query_request.chat_session_id)
                except ValueError:
                    await send("chat.error", safe_error_code="chat_session_not_found")
                    return
                chat_session = await chat_repository.get_chat_session(
                    db_session,
                    chat_session_id=chat_session_id,
                    organization_id=organization_id,
                    user_id=user_id,
                )
                if chat_session is None:
                    await send("chat.error", safe_error_code="chat_session_not_found")
                    return
            else:
                chat_session = await chat_repository.create_chat_session(
                    db_session,
                    organization_id=organization_id,
                    user_id=user_id,
                    title=query_request.question[:120],
                )

            conversation_id = str(chat_session.id)

            # ── Prompt template + injection check ─────────────────────────────
            answer_prompt_version: PromptTemplateVersion | None = None
            answer_prompt_template: str | None = None
            if query_request.scope_mode != "none":
                answer_prompt_version = await _resolve_answer_prompt_version(
                    db_session, organization_id=organization_id
                )
                answer_prompt_template = answer_prompt_version.content

            injection_check = _injection_guard.evaluate_request(
                objective="", question=query_request.question, document_query=None
            )

            # ── Language detection ────────────────────────────────────────────
            latencies_ms: dict[str, int] = {}
            total_started = perf_counter()
            embedding_model = _query_retrieval_service.embedding_model
            retrieved_chunks: list[RetrievedChunk] = []
            selected_chunks: list[RetrievedChunk] = []
            embedding_prompt_tokens = 0
            llm_prompt_tokens = 0
            llm_completion_tokens = 0
            llm_model: str | None = None
            llm_provider: str | None = None
            llm_fallback_used = False
            llm_fallback_from: str | None = None
            llm_fallback_to: str | None = None
            llm_fallback_reason: str | None = None
            llm_retry_count: int | None = None
            llm_cost_usd = None
            llm_latency_ms = 0
            answer = _NOT_FOUND_ANSWER
            citations: list[ChatCitationResponse] = []
            not_found = injection_check.blocked
            citation_validation_failed = False
            graph_context_result = GraphRetrievalResult()
            rerank_result: RerankResult | None = None

            chat_profile = await resolve_task_profile(
                db_session, organization_id=organization_id, task_type=TaskType.chat
            )
            rag_profile, _ = await resolve_profile_for_context(
                db_session,
                organization_id=organization_id,
                collection_id=None,
            )
            rerank_settings = _build_rerank_settings(
                dict(rag_profile.config) if rag_profile is not None else None
            )
            detected_language: str | None = None
            answer_language_used: str | None = None
            if settings.feature_enable_language_aware_rag and not injection_check.blocked:
                detected_language = detect_language(query_request.question)
                answer_language_used = resolve_answer_language(
                    mode=query_request.answer_language,
                    detected_language=detected_language,
                    workspace_default=settings.answer_language_workspace_default,
                )

            if injection_check.blocked:
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

            elif query_request.scope_mode == "none":
                # ── General chat (no retrieval) ───────────────────────────────
                embedding_model = None
                prompt = _prompt_service.build_general_prompt(
                    question=query_request.question, answer_language=answer_language_used
                )
                await send("generation.started")
                try:
                    llm_result = await _llm_service.generate_answer(
                        prompt=prompt, resolved_profile=chat_profile
                    )
                except (TransientLLMServiceError, PermanentLLMServiceError):
                    await send("chat.error", safe_error_code="generation_failed")
                    return
                llm_latency_ms = llm_result.latency_ms
                llm_model = llm_result.model_name
                llm_provider = llm_result.provider_key
                llm_fallback_used = llm_result.fallback_used
                llm_fallback_from = llm_result.fallback_from
                llm_fallback_to = llm_result.fallback_to
                llm_fallback_reason = llm_result.fallback_reason
                llm_prompt_tokens = llm_result.prompt_tokens
                llm_completion_tokens = llm_result.completion_tokens
                llm_cost_usd = llm_result.approximate_cost_usd
                answer = llm_result.answer if llm_result.answer.strip() else _NOT_FOUND_ANSWER
                not_found = llm_result.not_found or not answer.strip()
                await send("generation.delta", {"text": answer})
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
                # ── Full RAG pipeline ─────────────────────────────────────────
                final_top_k = query_request.top_k or settings.retrieval_final_top_k
                rerank_applied = bool(query_request.rerank and rerank_settings.enabled)
                rerank_input_limit = (
                    rerank_settings.max_input_candidates
                    or settings.rerank_default_input_candidates
                )
                retrieval_top_k = max(
                    final_top_k,
                    rerank_input_limit if rerank_applied else final_top_k,
                )

                # Embedding
                embed_started = perf_counter()
                try:
                    (
                        query_vector,
                        embedding_prompt_tokens,
                    ) = await _query_retrieval_service.embed_query(question=query_request.question)
                except Exception:
                    await send("chat.error", safe_error_code="query_embedding_failed")
                    return
                latencies_ms["embed"] = int((perf_counter() - embed_started) * 1000)

                # Retrieval
                await send("retrieval.started")
                retrieve_started = perf_counter()
                try:
                    retrieved_candidates = _query_retrieval_service.retrieve_candidates(
                        query_vector=query_vector,
                        organization_id=organization_id,
                        document_ids=document_ids,
                        initial_top_k=retrieval_top_k,
                        qdrant_client=_get_qdrant_client(),
                    )
                    retrieved_chunks = [_to_retrieved_chunk(c) for c in retrieved_candidates]
                    retrieved_chunks = await _source_provenance_service.filter_active_chunks(
                        db_session, organization_id=organization_id, chunks=retrieved_chunks
                    )
                    graph_enabled = await _resolve_graph_rag_enabled(
                        db_session, organization_id=organization_id
                    )
                    (
                        retrieved_chunks,
                        graph_context_result,
                    ) = await _augment_retrieval_with_graph_context(
                        db_session,
                        organization_id=organization_id,
                        question=query_request.question,
                        vector_chunks=retrieved_chunks,
                        allowed_document_ids=document_ids,
                        graph_enabled=graph_enabled,
                    )
                    retrieved_chunks = _with_original_ranks(retrieved_chunks)
                except Exception:
                    await send("chat.error", safe_error_code="retrieval_failed")
                    return
                latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)
                await send(
                    "retrieval.completed",
                    {"chunk_count": len(retrieved_chunks)},
                )

                # Reranking
                rerank_started = perf_counter()
                if rerank_applied:
                    await send("rerank.started")
                selected_chunks, rerank_result = await _rerank_chunks(
                    query=query_request.question,
                    chunks=retrieved_chunks,
                    enabled=rerank_applied,
                    final_top_k=final_top_k,
                    settings_override=rerank_settings,
                )
                latencies_ms["rerank"] = int((perf_counter() - rerank_started) * 1000)
                if rerank_applied:
                    await send("rerank.completed", {"selected_count": len(selected_chunks)})

                # Confidence pre-LLM
                confidence_signals = _to_confidence_signals(
                    chunks=selected_chunks, rerank_applied=rerank_applied
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
                    len(selected_chunks) == 0
                    or confidence_score < settings.confidence_not_found_threshold
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
                    _build_prompt(
                        question=query_request.question,
                        chunks=selected_chunks,
                        answer_language=answer_language_used,
                        template=answer_prompt_template,
                    )
                    if not not_found
                    else ""
                )
                latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

                if not not_found:
                    await send("generation.started")
                    try:
                        llm_result = await _llm_service.generate_answer(
                            prompt=prompt, resolved_profile=chat_profile
                        )
                    except (TransientLLMServiceError, PermanentLLMServiceError):
                        await send("chat.error", safe_error_code="generation_failed")
                        return
                    llm_latency_ms = llm_result.latency_ms
                    llm_model = llm_result.model_name
                    llm_provider = llm_result.provider_key
                    llm_fallback_used = llm_result.fallback_used
                    llm_fallback_from = llm_result.fallback_from
                    llm_fallback_to = llm_result.fallback_to
                    llm_fallback_reason = llm_result.fallback_reason
                    llm_retry_count = llm_result.retry_count
                    llm_prompt_tokens = llm_result.prompt_tokens
                    llm_completion_tokens = llm_result.completion_tokens
                    llm_cost_usd = llm_result.approximate_cost_usd
                    answer = llm_result.answer
                    await send("generation.delta", {"text": answer})

                    if (
                        llm_result.not_found
                        or not answer.strip()
                        or answer.strip() == _NOT_FOUND_ANSWER
                    ):
                        answer = _NOT_FOUND_ANSWER
                        not_found = True
                    else:
                        # Citation validation
                        await send("citation.validation.started")
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
                                    original_rank=chunk.original_rank,
                                    rerank_score=chunk.rerank_score,
                                    rerank_rank=chunk.rerank_rank,
                                    final_rank=chunk.final_rank,
                                )
                                for chunk in selected_chunks
                            ],
                            model_citations=llm_result.citations,
                        )
                        provenance_by_chunk_id = (
                            await _source_provenance_service.load_citation_details(
                                db_session,
                                organization_id=organization_id,
                                chunk_ids=[UUID(c.chunk_id) for c in citation_result.citations],
                            )
                        )
                        citations = [
                            _with_provenance(c, provenance_by_chunk_id.get(UUID(c.chunk_id)))
                            for c in citation_result.citations
                        ]
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
                        await send(
                            "citation.validation.completed",
                            {"citation_count": len(citations)},
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
            latencies_ms["total"] = answer_latency_ms
            rerank_diagnostics = rerank_result.diagnostics if rerank_result is not None else None

            # ── Persistence ───────────────────────────────────────────────────
            try:
                _ = await chat_repository.create_chat_message(
                    db_session,
                    chat_session_id=chat_session.id,
                    role=ChatRole.user.value,
                    content=query_request.question,
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
                    prompt_template_version_id=answer_prompt_version.id
                    if answer_prompt_version is not None
                    else None,
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
                        rerank_score=citation.rerank_score if rerank_applied else None,
                    )
                persisted_document_ids = (
                    [str(d) for d in document_ids] if document_ids is not None else []
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
                    provider_key=llm_provider,
                    task_type="chat",
                    retry_count=llm_retry_count,
                    fallback_used=llm_fallback_used,
                    metadata={
                        "chat_session_id": str(chat_session.id),
                        "assistant_message_id": str(assistant_message.id),
                        "document_ids": persisted_document_ids,
                        "confidence_score": confidence_score,
                        "confidence_category": confidence_category,
                        "not_found": not_found,
                        "citation_count": len(citations),
                        "latencies_ms": latencies_ms,
                        "answer_latency_ms": answer_latency_ms,
                        "rerank_applied": rerank_applied,
                        "rerank_enabled": rerank_settings.enabled,
                        "rerank_provider": rerank_diagnostics.provider_key if rerank_diagnostics else None,
                        "rerank_model": rerank_diagnostics.model_name if rerank_diagnostics else None,
                        "rerank_fallback_used": rerank_diagnostics.fallback_used if rerank_diagnostics else False,
                        "rerank_fallback_reason": rerank_diagnostics.fallback_reason if rerank_diagnostics else None,
                        "rerank_input_count": rerank_diagnostics.requested_count if rerank_diagnostics else 0,
                        "rerank_batch_count": rerank_diagnostics.batch_count if rerank_diagnostics else 0,
                        "rerank_prompt_tokens": rerank_diagnostics.prompt_tokens if rerank_diagnostics else 0,
                        "rerank_completion_tokens": rerank_diagnostics.completion_tokens if rerank_diagnostics else 0,
                        "rerank_total_tokens": rerank_diagnostics.total_tokens if rerank_diagnostics else 0,
                        "rerank_cost_usd": float(rerank_diagnostics.approximate_cost_usd) if rerank_diagnostics else None,
                        "transport": "websocket",
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
                        "transport": "websocket",
                    },
                )
                await db_session.commit()
            except Exception:
                await db_session.rollback()
                await send("chat.error", safe_error_code="chat_persistence_failed")
                return

            # ── Langfuse trace ────────────────────────────────────────────────
            trace_chat_query(
                ChatTraceMetadata(
                    request_id=request_id,
                    organization_id=str(organization_id),
                    user_id=str(user_id) if user_id is not None else "",
                    session_id=str(chat_session.id),
                    message_id=str(assistant_message.id),
                    question=query_request.question,
                    answer=answer,
                    scope_mode=query_request.scope_mode,
                    source_scope_label=source_scope_result.label,
                    feature_area="chat_ws",
                    retrieved_count=len(retrieved_chunks),
                    selected_count=len(selected_chunks),
                    rerank_applied=rerank_applied,
                    rerank_enabled=rerank_settings.enabled,
                    rerank_provider=rerank_diagnostics.provider_key if rerank_diagnostics else None,
                    rerank_model=rerank_diagnostics.model_name if rerank_diagnostics else None,
                    rerank_fallback_used=rerank_diagnostics.fallback_used if rerank_diagnostics else False,
                    rerank_fallback_reason=rerank_diagnostics.fallback_reason if rerank_diagnostics else None,
                    rerank_input_count=rerank_diagnostics.requested_count if rerank_diagnostics else 0,
                    rerank_batch_count=rerank_diagnostics.batch_count if rerank_diagnostics else 0,
                    rerank_prompt_tokens=rerank_diagnostics.prompt_tokens if rerank_diagnostics else 0,
                    rerank_completion_tokens=rerank_diagnostics.completion_tokens if rerank_diagnostics else 0,
                    rerank_total_tokens=rerank_diagnostics.total_tokens if rerank_diagnostics else 0,
                    rerank_cost_usd=rerank_diagnostics.approximate_cost_usd if rerank_diagnostics else None,
                    cited_count=len(citations),
                    not_found=not_found,
                    citation_validation_failed=citation_validation_failed,
                    confidence_score=confidence_score,
                    confidence_category=confidence_category,
                    llm_model=llm_model,
                    llm_provider=llm_provider,
                    embedding_model=embedding_model,
                    fallback_used=llm_fallback_used,
                    fallback_reason=llm_fallback_reason,
                    embedding_prompt_tokens=embedding_prompt_tokens,
                    llm_prompt_tokens=llm_prompt_tokens,
                    llm_completion_tokens=llm_completion_tokens,
                    llm_total_tokens=embedding_prompt_tokens
                    + llm_prompt_tokens
                    + llm_completion_tokens,
                    estimated_cost_usd=llm_cost_usd,
                    latencies_ms=dict(latencies_ms),
                    answer_latency_ms=answer_latency_ms,
                    detected_language=detected_language,
                    answer_language_used=answer_language_used,
                    prompt_template_key=PromptTemplateKey.answer_generation.value
                    if answer_prompt_version is not None
                    else None,
                    prompt_template_version=answer_prompt_version.version_number
                    if answer_prompt_version is not None
                    else None,
                )
            )
            log_query_event(
                event="query.completed",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                job_id=str(chat_session.id),
                status_code=200,
                not_found=not_found,
                confidence_score=confidence_score,
                confidence_category=confidence_category,
                retrieval_count=len(retrieved_chunks),
                selected_count=len(selected_chunks),
                graph_context_used=graph_context_result.graph_context_used,
                graph_context_reason=graph_context_result.graph_context_reason,
                transport="websocket",
            )

            # ── Final event ───────────────────────────────────────────────────
            final_response = ChatQueryResponse(
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
                    rerank_applied=rerank_applied,
                    rerank_enabled=rerank_settings.enabled,
                    rerank_provider=rerank_diagnostics.provider_key if rerank_diagnostics else None,
                    rerank_model=rerank_diagnostics.model_name if rerank_diagnostics else None,
                    rerank_fallback_used=rerank_diagnostics.fallback_used if rerank_diagnostics else False,
                    rerank_fallback_reason=rerank_diagnostics.fallback_reason if rerank_diagnostics else None,
                    rerank_input_count=rerank_diagnostics.requested_count if rerank_diagnostics else 0,
                    rerank_batch_count=rerank_diagnostics.batch_count if rerank_diagnostics else 0,
                    rerank_prompt_tokens=rerank_diagnostics.prompt_tokens if rerank_diagnostics else 0,
                    rerank_completion_tokens=rerank_diagnostics.completion_tokens if rerank_diagnostics else 0,
                    rerank_total_tokens=rerank_diagnostics.total_tokens if rerank_diagnostics else 0,
                    rerank_cost_usd=float(rerank_diagnostics.approximate_cost_usd)
                    if rerank_diagnostics
                    else None,
                    source_scope=source_scope_result.label,
                    graph_context_enabled=graph_context_result.graph_context_enabled,
                    graph_context_used=graph_context_result.graph_context_used,
                    graph_context_unavailable=graph_context_result.graph_context_unavailable,
                    graph_context_reason=graph_context_result.graph_context_reason,
                    graph_seed_entity_count=graph_context_result.graph_seed_entity_count,
                    graph_related_entity_count=graph_context_result.graph_related_entity_count,
                    graph_chunk_count=graph_context_result.graph_chunk_count,
                    graph_max_hops_used=graph_context_result.graph_max_hops_used,
                    graph_relation_types_used=list(graph_context_result.graph_relation_types_used),
                    embedding_model=embedding_model,
                    llm_model=llm_model,
                    llm_provider=llm_provider,
                    fallback_used=llm_fallback_used,
                    fallback_from=llm_fallback_from,
                    fallback_to=llm_fallback_to,
                    fallback_reason=llm_fallback_reason,
                    detected_language=detected_language,
                    answer_language_used=answer_language_used,
                    prompt_template_key=PromptTemplateKey.answer_generation.value
                    if answer_prompt_version is not None
                    else None,
                    prompt_template_version=answer_prompt_version.version_number
                    if answer_prompt_version is not None
                    else None,
                    prompt_template_version_id=str(answer_prompt_version.id)
                    if answer_prompt_version is not None
                    else None,
                ),
                created_at=assistant_message.created_at,
            )
            await send(
                "chat.completed",
                {"response": json.loads(final_response.model_dump_json())},
                message_id=str(assistant_message.id),
            )

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_query_event(
                event="query.failed.ws_unhandled",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                error=exc.__class__.__name__,
            )
            await send("chat.error", safe_error_code="internal_error")


@ws_router.websocket("/ws")
async def chat_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """WebSocket chat endpoint (F277). Feature-flagged via FEATURE_CHAT_WEBSOCKET_ENABLED."""
    if not settings.feature_chat_websocket_enabled:
        await websocket.close(code=4503, reason="WebSocket chat is not enabled")
        return

    # ── Auth ──────────────────────────────────────────────────────────────────
    async with SessionLocal() as auth_session:
        if not token:
            await websocket.close(code=4401, reason="Missing auth token")
            return
        principal = await _authenticate_ws_token(token, auth_session)

    if principal is None:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    user_id = principal.user_id

    # ── Role check ────────────────────────────────────────────────────────────
    allowed_roles = {
        OrganizationRole.owner.value,
        OrganizationRole.admin.value,
        OrganizationRole.member.value,
        OrganizationRole.viewer.value,
    }
    principal_roles = {r.strip() for r in (principal.roles or [])}
    if allowed_roles and not principal_roles.intersection(allowed_roles):
        await websocket.close(code=4403, reason="Insufficient role")
        return

    # ── Connection count guard ────────────────────────────────────────────────
    async with _ws_connection_lock:
        current = _ws_connection_counts.get(user_id, 0)
        if current >= settings.ws_chat_max_connections_per_user:
            await websocket.close(code=4429, reason="Too many connections")
            return
        _ws_connection_counts[user_id] = current + 1

    await websocket.accept()
    log_query_event(
        event="ws_chat.connection.opened",
        organization_id=principal.organization_id,
        user_id=user_id,
    )

    sequence = 0

    async def send_event(
        event_type: str,
        payload: dict[str, Any] | None = None,
        safe_error_code: str | None = None,
    ) -> None:
        nonlocal sequence
        sequence += 1
        evt = ChatWSOutboundEvent(
            event=event_type,  # type: ignore[arg-type]
            sequence=sequence,
            payload=payload,
            safe_error_code=safe_error_code,
        )
        await _ws_send(websocket, evt)

    active_task: asyncio.Task[None] | None = None
    heartbeat_task: asyncio.Task[None] | None = None

    async def run_heartbeat() -> None:
        interval = settings.ws_chat_heartbeat_interval_seconds
        while True:
            await asyncio.sleep(interval)
            await send_event("heartbeat.ping")

    try:
        await send_event("connection.ready")
        heartbeat_task = asyncio.create_task(run_heartbeat())
        request_id = secrets.token_hex(16)

        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=float(settings.ws_chat_idle_timeout_seconds),
                )
            except TimeoutError:
                break

            try:
                msg = ChatWSInboundMessage.model_validate_json(raw)
            except Exception:
                await send_event("chat.error", safe_error_code="invalid_message")
                continue

            if msg.command == "heartbeat.pong":
                continue

            if msg.command == "chat.cancel":
                if active_task and not active_task.done():
                    active_task.cancel()
                    try:
                        await active_task
                    except asyncio.CancelledError:
                        pass
                    active_task = None
                    await send_event("chat.cancelled")
                continue

            if msg.command == "chat.start":
                if active_task and not active_task.done():
                    await send_event("chat.error", safe_error_code="already_running")
                    continue

                # Rate limit per chat.start command.
                allowed = await _ws_rate_limit_chat(principal)
                if not allowed:
                    await send_event("chat.error", safe_error_code="rate_limit_exceeded")
                    continue

                request_id = msg.request_id or secrets.token_hex(16)
                payload_dict: dict[str, Any] = msg.payload or {}
                active_task = asyncio.create_task(
                    _run_ws_chat_pipeline(
                        websocket=websocket,
                        payload=payload_dict,
                        principal=principal,
                        request_id=request_id,
                        sequence_start=sequence,
                    )
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if heartbeat_task:
            heartbeat_task.cancel()
        if active_task and not active_task.done():
            active_task.cancel()
        async with _ws_connection_lock:
            _ws_connection_counts[user_id] = max(0, _ws_connection_counts.get(user_id, 1) - 1)
        log_query_event(
            event="ws_chat.connection.closed",
            organization_id=principal.organization_id,
            user_id=user_id,
        )


_answer_share_password_hasher = build_password_hasher(
    PasswordHashConfig(
        memory_cost=65536,
        time_cost=2,
        parallelism=2,
        hash_length=32,
        salt_length=16,
    )
)
_MAX_ACTIVE_ANSWER_SHARES = 10


def _to_answer_share_response(share: "AnswerShare") -> AnswerShareResponse:  # type: ignore[name-defined]  # noqa: F821
    from app.models.answer_share import AnswerShare as _AnswerShare  # noqa: F401

    return AnswerShareResponse(
        share_id=str(share.id),
        message_id=str(share.chat_message_id),
        token=share.token,
        access_mode=share.access_mode,  # type: ignore[arg-type]
        allowed_user_ids=list(share.allowed_user_ids or []),
        has_password=share.password_hash is not None,
        created_at=share.created_at,
        expires_at=share.expires_at,
        is_revoked=share.is_revoked,
        shared_by_user_id=str(share.shared_by_user_id),
    )


@router.post(
    "/messages/{message_id}/shares",
    response_model=AnswerShareResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_answer_share(
    message_id: str,
    payload: CreateAnswerShareRequest,
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
) -> AnswerShareResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)

    try:
        msg_id = UUID(message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc

    # Verify the message belongs to an assistant turn in this org.
    await _get_assistant_message_for_org(
        db_session, message_id=msg_id, organization_id=organization_id
    )

    active_count = await answer_share_repository.count_active_answer_shares(
        db_session,
        chat_message_id=msg_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if active_count >= _MAX_ACTIVE_ANSWER_SHARES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Maximum of {_MAX_ACTIVE_ANSWER_SHARES} active share links per answer reached.",
        )

    if payload.access_mode == "specific_users" and not payload.allowed_user_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="allowed_user_ids must not be empty when access_mode is 'specific_users'.",
        )

    from datetime import UTC, timedelta

    expires_at = (
        datetime.now(tz=UTC) + timedelta(hours=payload.expires_in_hours)
        if payload.expires_in_hours is not None
        else None
    )
    password_hash = (
        hash_password(payload.password, _answer_share_password_hasher) if payload.password else None
    )
    allowed_ids = payload.allowed_user_ids if payload.access_mode == "specific_users" else None

    token = secrets.token_urlsafe(32)
    share = await answer_share_repository.create_answer_share(
        db_session,
        chat_message_id=msg_id,
        organization_id=organization_id,
        shared_by_user_id=user_id,
        token=token,
        access_mode=payload.access_mode,
        allowed_user_ids=allowed_ids,
        password_hash=password_hash,
        expires_at=expires_at,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="answer.shared",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={
            "share_id": str(share.id),
            "access_mode": payload.access_mode,
            "has_password": password_hash is not None,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    await db_session.commit()
    await db_session.refresh(share)

    log_query_event(
        event="answer.shared",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=message_id,
        status_code=status.HTTP_201_CREATED,
    )
    return _to_answer_share_response(share)


@router.get("/messages/{message_id}/shares", response_model=AnswerShareListResponse)
async def list_answer_shares(
    message_id: str,
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
) -> AnswerShareListResponse:
    user_id, organization_id = _principal_user_and_org(principal)

    try:
        msg_id = UUID(message_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Message not found"
        ) from exc

    await _get_assistant_message_for_org(
        db_session, message_id=msg_id, organization_id=organization_id
    )

    shares = await answer_share_repository.list_active_answer_shares(
        db_session,
        chat_message_id=msg_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    items = [_to_answer_share_response(s) for s in shares]
    return AnswerShareListResponse(items=items, total=len(items))


@router.delete(
    "/messages/{message_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_answer_share(
    message_id: str,
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
        msg_id = UUID(message_id)
        share_uuid = UUID(share_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Share not found"
        ) from exc

    revoked = await answer_share_repository.revoke_answer_share(
        db_session,
        share_id=share_uuid,
        chat_message_id=msg_id,
        organization_id=organization_id,
        user_id=user_id,
    )
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="answer.share.revoked",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={"share_id": share_id},
    )
    await db_session.commit()

    log_query_event(
        event="answer.share.revoked",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=message_id,
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.get("/answer-shared/{token}", response_model=SharedAnswerResponse)
async def get_shared_answer(
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
    password: Annotated[str | None, Query(max_length=128)] = None,
) -> SharedAnswerResponse:
    viewer_user_id, organization_id = _principal_user_and_org(principal)
    request_id = _request_id_from_request(request)

    share = await answer_share_repository.get_answer_share_by_token(
        db_session,
        token=token,
        organization_id=organization_id,
    )
    if share is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found, expired, or revoked.",
        )

    # Password check
    if share.password_hash is not None:
        if not password or not verify_password(
            password, share.password_hash, _answer_share_password_hasher
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A valid password is required to access this share link.",
            )

    # Specific-users access check
    if share.access_mode == "specific_users":
        allowed = [str(uid) for uid in (share.allowed_user_ids or [])]
        if str(viewer_user_id) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not in the allowed-users list for this share link.",
            )

    # Load the assistant message and its preceding user message.
    from sqlalchemy import select as _select

    from app.models.chat import ChatMessage as _ChatMessage

    assistant_result = await db_session.execute(
        _select(_ChatMessage).where(_ChatMessage.id == share.chat_message_id)
    )
    assistant_msg = assistant_result.scalar_one_or_none()
    if assistant_msg is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Share link not found, expired, or revoked.",
        )

    # Find the user message that immediately precedes this assistant message in the same session.
    user_msg_result = await db_session.execute(
        _select(_ChatMessage)
        .where(
            _ChatMessage.chat_session_id == assistant_msg.chat_session_id,
            _ChatMessage.role == "user",
            _ChatMessage.created_at < assistant_msg.created_at,
        )
        .order_by(_ChatMessage.created_at.desc())
        .limit(1)
    )
    user_msg = user_msg_result.scalar_one_or_none()
    question_text = user_msg.content if user_msg else ""

    # Load citations — include snippet/filename only, not document_id/chunk_id (safety).
    citation_rows = await chat_repository.list_citations_for_message_with_filename(
        db_session,
        chat_message_id=assistant_msg.id,
    )
    safe_citations = [
        SharedAnswerCitationResponse(
            filename=filename,
            page_number=citation.page_number,
            text_snippet=citation.text_snippet,
        )
        for citation, filename in citation_rows
    ]

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=str(viewer_user_id),
        action="answer.share.viewed",
        resource_type="chat_message",
        resource_id=share.chat_message_id,
        request_id=request_id,
        metadata={
            "share_id": str(share.id),
            "share_owner_user_id": str(share.shared_by_user_id),
            "access_mode": share.access_mode,
        },
    )
    await db_session.commit()

    log_query_event(
        event="answer.share.viewed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(share.chat_message_id),
        status_code=status.HTTP_200_OK,
    )
    return SharedAnswerResponse(
        question=question_text,
        answer=assistant_msg.content,
        citations=safe_citations,
        confidence_score=assistant_msg.confidence_score,
        confidence_category=_confidence_category_from_score(assistant_msg.confidence_score),
        shared_at=share.created_at,
        expires_at=share.expires_at,
        access_mode=share.access_mode,  # type: ignore[arg-type]
    )
