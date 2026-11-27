import asyncio
import json
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Annotated, Any
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

from app.application.chat.citation_access import filter_chunks_by_cite_access
from app.application.chat.message_citations import (
    load_message_citations,
    persist_answer_citations,
)
from app.application.chat.pipeline.controls import (
    _NOT_FOUND_ANSWER,
    _augment_retrieval_with_graph_context,
    _build_conflict_detection_chunks,
    _build_prompt,
    _build_rerank_settings,
    _rerank_chunks,
    _resolve_answer_prompt_version,
    _resolve_graph_rag_enabled,
    _resolve_grounded_verification_controls,
    _resolve_planner_critic_controls,
    _resolve_query_rewrite_preview_enabled,
    _resolve_tree_search_reasoning_enabled,
)
from app.application.chat.pipeline.deps import default_deps
from app.application.chat.pipeline.errors import _safe_http_error
from app.application.chat.pipeline.provider_proxies import (  # noqa: F401 (re-export)
    _ChatCompletionProviderProxy,
    _EmbeddingProviderProxy,
    bind_openai_client_proxies,
)
from app.application.chat.quota import (
    chat_quota_denial,
    ensure_chat_quota,
    record_chat_usage,
)
from app.application.chat.scope_inventory import (  # noqa: F401 (re-export)
    _SCOPE_INVENTORY_MAX_CITATIONS,
    _SCOPE_INVENTORY_MAX_LISTED_DOCUMENTS,
    _SCOPE_INVENTORY_SNIPPET_CHARS,
    ScopeInventoryDocument,
    ScopeInventoryResult,
    _build_scope_inventory_answer,
    _build_scope_inventory_result,
    _filter_authorized_document_ids_for_chat,
    _filter_authorized_documents_for_chat,
    _is_scope_inventory_question,
    _scope_inventory_snippet,
)
from app.application.chat.ws_auth import authenticate_ws_handshake
from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.auth.passwords import (
    PasswordHashConfig,
    build_password_hasher,
    hash_password,
    verify_password,
)
from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.core.langfuse_tracer import ChatTraceMetadata, trace_chat_query
from app.core.logging import log_query_event
from app.db.session import SessionLocal, get_db_session
from app.domains.ai.profile.schemas import TaskType
from app.domains.ai.profile.service import resolve_task_profile
from app.domains.ai_response_policy.services.policy_engine import (
    PolicyEvaluationResult as AiPolicyEvaluationResult,
)
from app.domains.chat.repositories.answer_share import AnswerShareRepository
from app.domains.chat.repositories.chat import (
    MESSAGE_SORT_NAME,
    SESSION_SORT_NAME,
    message_sort_key,
    session_sort_key,
)
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
    ChatConflictPairResponse,
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
from app.domains.chat.schemas.trust_metadata import (
    AnswerTrustMetadataResponse,
)
from app.domains.chat.services.answer_critic_service import CriticResult
from app.domains.chat.services.answer_planner_service import (
    STRATEGY_LABELS,
    PlannerResult,
)
from app.domains.chat.services.answer_refiner_service import RefinerResult
from app.domains.chat.services.chat_values import (
    _decimal_to_float_or_none,
    _list_or_empty,
    _parse_uuid_or_none,
)
from app.domains.chat.services.citation_enrichment import (
    _build_conflict_context,
    _with_conflict_status,
    _with_extraction_quality,
    _with_freshness,
    _with_ocr_quality,
    _with_provenance,
    _with_table_metadata,
)
from app.domains.chat.services.citation_service import (
    CitationBuildResult,
    CitationContextChunk,
)
from app.domains.chat.services.confidence_calibration import (  # noqa: F401 (re-export)
    _EXTRACTION_CONFIDENCE_WARN_THRESHOLD,
    _EXTRACTION_WARNING_PROFILES,
    _PROCESSING_INCOMPLETE_STATUSES,
    _TABLE_CONFIDENCE_LOW_THRESHOLD,
    _TABLE_CONFIDENCE_VERY_LOW_THRESHOLD,
    _build_evidence_quality_inputs,
    _build_evidence_quality_record,
    _compute_conflict_multiplier,
    _compute_extraction_quality_multiplier,
    _compute_freshness_multiplier,
    _compute_ocr_quality_multiplier,
    _compute_table_quality_multiplier,
    _confidence_category_from_score,
    _to_confidence_signals,
)
from app.domains.chat.services.conflict_detection_service import (
    ConflictDetectionResult,
)
from app.domains.chat.services.context_packer_service import (
    ContextPackerConfig,
    ContextPackResult,
)
from app.domains.chat.services.graph_retrieval_service import (  # noqa: F401 (re-export)
    GraphRetrievalResult,
    GraphRetrievalService,
    GraphRetrievedChunk,
)
from app.domains.chat.services.grounded_answer_verifier import (
    GroundedVerifierResult,
    VerifierChunk,
)
from app.domains.chat.services.language_service import detect_language, resolve_answer_language
from app.domains.chat.services.llm_service import (
    LLMAnswerResult,
    PermanentLLMServiceError,
    TransientLLMServiceError,
)
from app.domains.chat.services.parallel_retrieval_optimizer import (
    ParallelRetrievalBudget,
    ParallelRetrievalResult,
)
from app.domains.chat.services.parent_context_expansion_service import (
    ParentExpansionResult,
)
from app.domains.chat.services.query_intent_service import (  # noqa: F401 (re-export)
    _QUERY_INTENT_LABELS,
    _build_query_interpretation_record,
    _build_retrieval_filters,
    _build_retrieval_profile_scope,
    _build_search_mode,
    _guidance_label,
    _infer_query_intent,
    _query_complexity,
)
from app.domains.chat.services.query_rewriting_service import (
    QueryRewritingResult,
)
from app.domains.chat.services.rerank_service import (
    RerankResult,
)
from app.domains.chat.services.retrieval_strategy_router import (
    FeatureAvailability,
    RetrievalRouteResult,
)
from app.domains.chat.services.retrieved_chunk import (  # noqa: F401 (re-export)
    RetrievedChunk,
    _hybrid_to_retrieved_chunk,
    _merge_retrieved_chunks,
    _to_graph_retrieved_chunk,
    _to_retrieved_chunk,
    _with_original_ranks,
)
from app.domains.chat.services.source_freshness_service import (
    DocumentTrustData,
)
from app.domains.chat.services.table_retrieval_service import (
    TableBoostResult,
)
from app.domains.chat.services.tool_orchestrator import (
    ToolOrchestrationResult,
)
from app.domains.chat.services.tree_search_service import (
    TreeSearchCandidateScore,
)
from app.domains.chat.services.trust_metadata_builder import _build_trust_metadata
from app.domains.chat.services.trust_records import (  # noqa: F401 (re-export)
    _build_claim_support_records,
    _build_parallel_branch_records,
    _build_planner_critic_record,
    _build_rerank_score_range,
    _build_retrieval_diagnostics_payload,
    _build_retrieval_method_record,
    _build_tool_orchestration_record,
    _build_verifier_citations,
)
from app.domains.rag_profiles.schemas.rag_profiles import RagProfileConfig
from app.domains.rag_profiles.services.rag_profile_service import resolve_profile_for_context
from app.models.enums import ChatRole, OrganizationRole, PromptTemplateKey
from app.models.prompt_template import PromptTemplateVersion
from app.rate_limit import RateLimitScope, enforce_rate_limit
from app.rate_limit.counter import RateLimitDecision, consume_rate_limit
from app.shared.pagination import encode_cursor, resolve_page_request, split_page

router = APIRouter(prefix="/chat", tags=["chat"])
# Separate router for WebSocket — must NOT be under protected_router because
# the browser WebSocket API cannot send an Authorization header during the HTTP
# upgrade, so FastAPI's router-level get_current_principal dependency would fail.
ws_router = APIRouter(prefix="/chat", tags=["chat"])
chat_repository = default_deps.chat_repository
share_repository = ChatShareRepository()
answer_share_repository = AnswerShareRepository()
feedback_repository = FeedbackRepository()
usage_repository = default_deps.usage_repository
audit_log_service = default_deps.audit_log_service

_MAX_ACTIVE_SHARES_PER_SESSION = 10
# Legacy module names of the pipeline singletons (contract 4.2.2): the same objects as
# ``default_deps``, so patching an attribute through ``chat_api`` patches the pipeline.
_query_retrieval_service = default_deps.query_retrieval_service
_keyword_retrieval_service = default_deps.keyword_retrieval_service
_hybrid_retrieval_service = default_deps.hybrid_retrieval_service
_source_scope_service = default_deps.source_scope_service
_rerank_service = default_deps.rerank_service
_prompt_service = default_deps.prompt_service
_prompt_template_service = default_deps.prompt_template_service
_citation_service = default_deps.citation_service
_source_provenance_service = default_deps.source_provenance_service
_confidence_service = default_deps.confidence_service
_conflict_detection_service = default_deps.conflict_detection_service
_graph_retrieval_service = default_deps.graph_retrieval_service
_feature_flag_service = default_deps.feature_flag_service
# Rebindable: tests set it to a fake OpenAI client; the proxies read it on every call.
_openai_client: Any | None = None

_llm_service = default_deps.llm_service
_injection_guard = default_deps.injection_guard
_query_rewriting_service = default_deps.query_rewriting_service
_grounded_verifier = default_deps.grounded_verifier
_answer_mode_service = default_deps.answer_mode_service
_answer_planner = default_deps.answer_planner
_answer_critic = default_deps.answer_critic
_answer_refiner = default_deps.answer_refiner
_authorization_service = default_deps.authorization_service
_source_freshness_service = default_deps.source_freshness_service
_table_retrieval_service = default_deps.table_retrieval_service
_ocr_quality_service = default_deps.ocr_quality_service
_parent_context_expansion_service = default_deps.parent_context_expansion_service
_parallel_retrieval_optimizer = default_deps.parallel_retrieval_optimizer
_context_packer_service = default_deps.context_packer_service
_retrieval_strategy_router = default_deps.retrieval_strategy_router
_chat_tool_orchestrator = default_deps.chat_tool_orchestrator
_tree_search_service = default_deps.tree_search_service
_chat_tool_policy_repo = default_deps.chat_tool_policy_repo
_document_repository_for_trust = default_deps.document_repository_for_trust
_ai_policy_repo = default_deps.ai_policy_repo
_ai_policy_engine = default_deps.ai_policy_engine
bind_openai_client_proxies(
    llm_service=_llm_service,
    query_retrieval_service=_query_retrieval_service,
    client_getter=lambda: _openai_client,
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


# F315 — evidence quality thresholds


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
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    include_total: bool | None = None,
) -> ChatSessionListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    normalized_search = search.strip() if search and search.strip() else None
    page = resolve_page_request(
        cursor=cursor, offset=offset, include_total=include_total, sort_name=SESSION_SORT_NAME
    )
    sessions, has_more = split_page(
        await chat_repository.list_chat_sessions(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            limit=limit + 1,
            offset=offset,
            search=normalized_search,
            keyset=page.keyset,
        ),
        limit,
    )
    total = (
        await chat_repository.count_chat_sessions(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            search=normalized_search,
        )
        if page.include_total
        else None
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
        next_cursor=(
            encode_cursor(SESSION_SORT_NAME, session_sort_key(sessions[-1])) if has_more else None
        ),
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
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    include_total: bool | None = None,
) -> ChatSessionMessageListResponse:
    user_id, organization_id = _principal_user_and_org(principal)
    page = resolve_page_request(
        cursor=cursor, offset=offset, include_total=include_total, sort_name=MESSAGE_SORT_NAME
    )
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

    messages, has_more = split_page(
        await chat_repository.list_chat_messages(
            db_session,
            chat_session_id=chat_session.id,
            limit=limit + 1,
            offset=offset,
            keyset=page.keyset,
        ),
        limit,
    )
    total = (
        await chat_repository.count_chat_messages(
            db_session,
            chat_session_id=chat_session.id,
        )
        if page.include_total
        else None
    )

    citations_by_message = await load_message_citations(
        db_session,
        messages=messages,
        organization_id=organization_id,
        decorate=_with_provenance,
        repository=chat_repository,
        provenance_service=_source_provenance_service,
    )
    items = [
        ChatSessionMessageResponse(
            message_id=str(message.id),
            role=message.role,
            content=message.content,
            confidence_score=message.confidence_score,
            confidence_category=_confidence_category_from_score(message.confidence_score),
            citations=citations_by_message.get(message.id, []),
            created_at=message.created_at,
        )
        for message in messages
    ]

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
        next_cursor=(
            encode_cursor(MESSAGE_SORT_NAME, message_sort_key(messages[-1])) if has_more else None
        ),
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
    await ensure_chat_quota(db_session, organization_id=organization_id, transport="http")
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
    document_ids = await _filter_authorized_document_ids_for_chat(
        db_session,
        principal=principal,
        organization_id=organization_id,
        user_id=user_id,
        user_roles=user_roles,
        document_ids=document_ids,
    )

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

    # AI response policy pre-generation check — topic blocking (F268).
    _ai_org_policy = await _ai_policy_repo.get_active(db_session, organization_id=organization_id)
    # Resolve collection override when the query is scoped to a single collection.
    _ai_collection_override = None
    _ai_policy_collection_id: UUID | None = None
    if _ai_org_policy is not None and payload.source_scope is not None:
        # source_scope may be a collection-id string when scoping to one collection.
        try:
            _ai_policy_collection_id = UUID(str(payload.source_scope))
            _ai_collection_override = await _ai_policy_repo.get_collection_override(
                db_session,
                org_policy_id=_ai_org_policy.id,
                collection_id=_ai_policy_collection_id,
            )
        except (ValueError, AttributeError):
            pass
    _ai_effective_policy = _ai_policy_engine.resolve(_ai_org_policy, _ai_collection_override)
    _ai_pre_result = _ai_policy_engine.evaluate_pre_generation(
        payload.question, _ai_effective_policy
    )
    if _ai_pre_result.blocked and not injection_check.blocked:
        log_query_event(
            event="query.rejected.policy_topic_blocked",
            organization_id=principal.organization_id,
            user_id=principal.user_id,
            job_id=str(chat_session.id),
            status_code=status.HTTP_200_OK,
            violated_rules=_ai_pre_result.violated_rules,
        )

    answer_mode_result = _answer_mode_service.classify(question=payload.question)
    scope_inventory_requested = _is_scope_inventory_question(payload.question)
    if answer_mode_result.mode == "grounded" and not scope_inventory_requested:
        answer_prompt_version = await _resolve_answer_prompt_version(
            db_session,
            organization_id=organization_id,
        )
        answer_prompt_template = answer_prompt_version.content

    latencies_ms: dict[str, int] = {}
    total_started = perf_counter()
    embedding_model = _query_retrieval_service.embedding_model
    rag_profile, rag_profile_source = await resolve_profile_for_context(
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
    not_found = injection_check.blocked or _ai_pre_result.blocked
    citation_validation_failed = False
    verification_failed = False
    grounded_verifier_result: GroundedVerifierResult | None = None
    graph_context_result = GraphRetrievalResult()
    rerank_result: RerankResult | None = None
    query_rewrite_result: QueryRewritingResult | None = None
    query_rewrite_preview_enabled = settings.feature_enable_query_rewrite_preview
    _freshness_trust_map: dict[str, DocumentTrustData] = {}
    _freshness_stale_ids: frozenset[str] = frozenset()
    freshness_filter_enabled = False
    freshness_excluded_count = 0
    freshness_boosted_count = 0
    freshness_stale_count = 0
    freshness_unreviewed_count = 0
    freshness_deprecated_count = 0
    freshness_draft_count = 0
    freshness_all_excluded_fallback = False
    table_boost_enabled = False
    table_boost_applied = False
    table_boost_count = 0
    table_chunk_count = 0
    table_query_detected = False
    _table_boost_result: TableBoostResult | None = None
    _ocr_docs: list = []
    _ocr_quality_map: dict[str, str] = {}
    ocr_quality_downranking_enabled = False
    ocr_low_confidence_chunk_count = 0
    _parent_expansion_result: ParentExpansionResult | None = None
    _parent_context_map: dict[str, str] = {}
    parent_context_expansion_enabled = False
    parent_context_child_hit_count = 0
    parent_context_expanded_count = 0
    parent_context_tokens_used = 0
    conflict_detection_enabled = False
    conflict_detection_applied = False
    conflict_detection_latency_ms = 0
    rerank_applied = False
    final_top_k = payload.top_k or settings.retrieval_final_top_k
    grounded_verification_enabled = False
    grounded_verification_mode: str | None = None
    grounded_verification_threshold: float | None = None
    conflict_detection_result = ConflictDetectionResult(
        conflict_detected=False,
        agreement_level="full",
    )
    # Calibration multipliers (F310) — updated after freshness/OCR/conflict data is available
    _freshness_multiplier: float = 1.0
    _ocr_quality_multiplier: float = 1.0
    _conflict_multiplier: float = 1.0
    # AI response policy state (F268)
    _ai_policy_result: AiPolicyEvaluationResult = AiPolicyEvaluationResult()
    # Planner-critic-refiner pipeline state (F339)
    planner_result: PlannerResult | None = None
    critic_result: CriticResult | None = None
    refiner_result: RefinerResult | None = None
    _pcr_enabled: bool = False
    _pcr_mode: str = "high_risk_only"
    _pcr_high_risk: frozenset[str] = frozenset()
    # Strict context packing state (F340)
    _context_pack_result: ContextPackResult | None = None
    context_packing_rejected_count: int = 0
    # Dynamic retrieval strategy routing state (F341)
    _route_result: RetrievalRouteResult | None = None
    parallel_result: ParallelRetrievalResult | None = None
    # Adaptive tool orchestration state (F342)
    _orchestration_result: ToolOrchestrationResult | None = None

    # Resolve the effective model profile for this organisation (F223).
    chat_profile = await resolve_task_profile(
        db_session,
        organization_id=organization_id,
        task_type=TaskType.chat,
    )

    # Planner: classify question strategy and flag high-risk answers (F339).
    # Runs synchronously before retrieval — keyword heuristics only, <1 ms.
    # Also runs when dynamic routing is enabled (F341) so the router has a strategy.
    _pcr_enabled, _pcr_mode, _pcr_high_risk = _resolve_planner_critic_controls(
        RagProfileConfig.model_validate(dict(rag_profile.config))
        if rag_profile is not None
        else None,
    )
    _routing_enabled = settings.feature_enable_dynamic_retrieval_routing
    if (
        (_pcr_enabled or _routing_enabled)
        and not injection_check.blocked
        and not not_found
        and answer_mode_result.mode == "grounded"
        and not scope_inventory_requested
    ):
        planner_result = _answer_planner.classify(
            question=payload.question,
            graph_context_available=settings.feature_enable_graph_rag,
            connector_search_scope=False,
            high_risk_strategies_override=_pcr_high_risk,
        )

    # Dynamic retrieval strategy routing (F341).
    # Selects the best retrieval method based on the planner strategy,
    # feature-flag availability, and any admin / user overrides.
    if (
        _routing_enabled
        and not injection_check.blocked
        and not not_found
        and answer_mode_result.mode == "grounded"
        and not scope_inventory_requested
    ):
        _profile_cfg_for_routing = (
            RagProfileConfig.model_validate(dict(rag_profile.config))
            if rag_profile is not None
            else None
        )
        _route_result = _retrieval_strategy_router.route(
            planner_strategy=planner_result.strategy if planner_result is not None else "standard",
            features=FeatureAvailability(
                hybrid_retrieval_enabled=settings.feature_enable_hybrid_retrieval,
                graph_rag_enabled=settings.feature_enable_graph_rag,
                parent_context_expansion_enabled=settings.feature_enable_parent_context_expansion,
                keyword_retrieval_enabled=settings.feature_enable_hybrid_retrieval,
            ),
            profile_override=(
                _profile_cfg_for_routing.retrieval_strategy_override
                if _profile_cfg_for_routing is not None
                else None
            ),
            request_override=payload.retrieval_strategy_override,
            allow_user_override=settings.feature_enable_retrieval_strategy_user_override,
        )

    # Adaptive tool orchestration (F342): authorize pipeline tools for this query.
    # Loads org-level disabled tools from DB, then resolves authorization synchronously.
    if (
        settings.feature_enable_chat_tool_orchestration
        and not injection_check.blocked
        and not not_found
        and answer_mode_result.mode == "grounded"
        and not scope_inventory_requested
    ):
        _orchestration_feature_availability: dict[str, bool] = {
            "feature_enable_connectors": settings.feature_enable_connectors,
            "feature_enable_graph_rag": settings.feature_enable_graph_rag,
        }
        _orchestration_overrides = await _chat_tool_policy_repo.list_by_organization(
            db_session, organization_id=organization_id
        )
        _orchestration_disabled: frozenset[str] = frozenset(
            o.tool_name for o in _orchestration_overrides if not o.enabled
        )
        _orchestration_result = _chat_tool_orchestrator.orchestrate(
            planner_strategy=planner_result.strategy if planner_result is not None else "standard",
            principal=principal,
            feature_availability=_orchestration_feature_availability,
            disabled_tool_names=_orchestration_disabled,
            source_scope_mode=payload.scope_mode,
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

    # Query rewriting and decomposition (F295).
    # Runs after language detection so the detected language is available for context.
    # Scope filters (document_ids, org tenancy) are applied in the retrieval layer and
    # are never altered here — rewriting cannot widen access.
    if (
        settings.feature_enable_query_rewriting
        and not injection_check.blocked
        and answer_mode_result.mode == "grounded"
        and not scope_inventory_requested
    ):
        _profile_rewriting = True
        _profile_decomposition = True
        _profile_max_sub_queries: int | None = None
        if rag_profile is not None:
            _profile_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
            _profile_rewriting = _profile_cfg.query_rewriting_enabled
            _profile_decomposition = _profile_cfg.query_decomposition_enabled
            _profile_max_sub_queries = _profile_cfg.query_rewriting_max_sub_queries
        query_rewrite_preview_enabled = await _resolve_query_rewrite_preview_enabled(
            db_session,
            organization_id=organization_id,
        )
        query_rewrite_result = await _query_rewriting_service.rewrite(
            payload.question,
            profile_rewriting_enabled=_profile_rewriting,
            profile_decomposition_enabled=_profile_decomposition,
            max_sub_queries=_profile_max_sub_queries,
        )
        if query_rewrite_result.rewriting_applied or query_rewrite_result.decomposition_applied:
            log_query_event(
                event="query.rewriting.applied",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                strategy=query_rewrite_result.strategy,
                rewriting_applied=query_rewrite_result.rewriting_applied,
                decomposition_applied=query_rewrite_result.decomposition_applied,
                sub_query_count=len(query_rewrite_result.sub_queries),
            )

    if injection_check.blocked or _ai_pre_result.blocked:
        # Question blocked by injection heuristics or AI response policy topic check.
        embedding_model = None
        if _ai_pre_result.blocked and not injection_check.blocked:
            _ai_policy_result = _ai_pre_result
            answer = _ai_pre_result.refusal_message or _NOT_FOUND_ANSWER
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
    elif scope_inventory_requested:
        embedding_model = None
        retrieve_started = perf_counter()
        inventory_result = await _build_scope_inventory_result(
            db_session,
            principal=principal,
            organization_id=organization_id,
            user_id=user_id,
            user_roles=user_roles,
            document_ids=document_ids,
        )
        latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)
        retrieved_chunks = inventory_result.retrieved_chunks
        selected_chunks = inventory_result.retrieved_chunks
        citations = inventory_result.citations
        answer = _build_scope_inventory_answer(
            inventory=inventory_result,
            source_scope_result=source_scope_result,
        )
        not_found = inventory_result.total_count == 0
        confidence_signals = _to_confidence_signals(
            chunks=selected_chunks,
            rerank_applied=False,
        )
        confidence_result = _confidence_service.score(
            chunks=confidence_signals,
            citation_count=len(citations),
            citation_validation_score=1.0,
            not_found_signal=not_found,
        )
        confidence_score = confidence_result.score
        confidence_category = confidence_result.category
        confidence_explanation = confidence_result.explanation
    elif answer_mode_result.mode == "guidance":
        # Guidance mode: skip retrieval and answer with safe Rudix product help only.
        embedding_model = None
        prompt = _prompt_service.build_guidance_prompt(
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
        citations = []
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
        rerank_input_limit = (
            rerank_settings.max_input_candidates or settings.rerank_default_input_candidates
        )
        retrieval_top_k = max(final_top_k, rerank_input_limit if rerank_applied else final_top_k)

        # Determine which queries to use for retrieval.
        # For rewrite: use the single rewritten query.
        # For decompose: use primary_query + each sub_query for parallel retrieval.
        # For original (or no rewriting): use the user's question unchanged.
        if query_rewrite_result is not None and query_rewrite_result.decomposition_applied:
            _retrieval_queries = [
                query_rewrite_result.primary_query,
                *list(query_rewrite_result.sub_queries),
            ]
        elif query_rewrite_result is not None and query_rewrite_result.rewriting_applied:
            _retrieval_queries = [query_rewrite_result.primary_query]
        else:
            _retrieval_queries = [payload.question]

        retrieve_started = perf_counter()
        try:
            graph_enabled = await _resolve_graph_rag_enabled(
                db_session, organization_id=organization_id
            )
            _route_wants_vector_only = (
                _route_result is not None and _route_result.method == "vector"
            )
            _effective_hybrid = (
                settings.feature_enable_hybrid_retrieval and not _route_wants_vector_only
            )
            _parallel_budget = ParallelRetrievalBudget(
                max_parallel_calls=settings.retrieval_parallel_max_calls,
                timeout_ms=settings.retrieval_parallel_timeout_ms,
                max_retry_attempts=settings.retrieval_parallel_max_retry_attempts,
                max_total_tokens=settings.retrieval_parallel_max_total_tokens,
                max_total_cost_usd=(
                    None
                    if settings.retrieval_parallel_max_total_cost_usd is None
                    else settings.retrieval_parallel_max_total_cost_usd
                ),
            )
            parallel_result = await _parallel_retrieval_optimizer.execute(
                session=db_session,
                organization_id=organization_id,
                document_ids=document_ids,
                queries=_retrieval_queries,
                query_retrieval_service=_query_retrieval_service,
                keyword_retrieval_service=_keyword_retrieval_service,
                graph_retrieval_service=_graph_retrieval_service,
                graph_enabled=graph_enabled,
                keyword_enabled=_effective_hybrid,
                qdrant_client=_get_qdrant_client(),
                top_k=retrieval_top_k,
                exact_match_boost=settings.hybrid_retrieval_exact_match_boost,
                budget=_parallel_budget,
                index_versions=settings.active_index_versions,
            )
            embedding_model = parallel_result.embedding_model or embedding_model
            embedding_prompt_tokens = parallel_result.total_embedding_prompt_tokens
            graph_context_result = parallel_result.graph_result

            _merged_chunks: dict[str, RetrievedChunk] = {}
            _primary_query_for_kw = _retrieval_queries[0]
            for record in parallel_result.query_records:
                retrieved_candidates = record.vector_candidates
                if _effective_hybrid and record.keyword_candidates is not None:
                    hybrid_result = _hybrid_retrieval_service.merge(
                        vector_candidates=retrieved_candidates,
                        keyword_candidates=record.keyword_candidates.candidates,
                        exact_match_tokens=record.keyword_candidates.exact_match_tokens,
                        vector_weight=settings.hybrid_retrieval_vector_weight,
                        rrf_k=settings.hybrid_retrieval_rrf_k,
                        exact_match_boost=settings.hybrid_retrieval_exact_match_boost,
                    )
                    batch_chunks = [_hybrid_to_retrieved_chunk(c) for c in hybrid_result.candidates]
                    if record.query == _primary_query_for_kw:
                        hybrid_retrieval_enabled = True
                        hybrid_vector_hit_count = hybrid_result.vector_hit_count
                        hybrid_keyword_hit_count = hybrid_result.keyword_hit_count
                        hybrid_exact_match_tokens = hybrid_result.exact_match_tokens
                else:
                    batch_chunks = [
                        _to_retrieved_chunk(candidate) for candidate in retrieved_candidates
                    ]

                for chunk in batch_chunks:
                    key = str(chunk.chunk_id)
                    if (
                        key not in _merged_chunks
                        or chunk.similarity_score > _merged_chunks[key].similarity_score
                    ):
                        _merged_chunks[key] = chunk

            retrieved_chunks = sorted(
                _merged_chunks.values(), key=lambda c: c.similarity_score, reverse=True
            )

            retrieved_chunks = await _source_provenance_service.filter_active_chunks(
                db_session,
                organization_id=organization_id,
                chunks=retrieved_chunks,
            )

            # Citation-level authorization: remove chunks the principal cannot cite.
            retrieved_chunks = await filter_chunks_by_cite_access(
                db_session,
                principal=principal,
                organization_id=organization_id,
                user_id=user_id,
                user_roles=user_roles,
                chunks=retrieved_chunks,
            )

            retrieved_chunks, graph_context_result = await _augment_retrieval_with_graph_context(
                db_session,
                organization_id=organization_id,
                question=payload.question,
                vector_chunks=retrieved_chunks,
                allowed_document_ids=document_ids,
                graph_enabled=graph_enabled,
                graph_result=graph_context_result,
            )
            retrieved_chunks = _with_original_ranks(retrieved_chunks)

            # Source freshness filtering and trust-score boosting (F297).
            # Resolve freshness settings from RAG profile; defaults are safe (boost on, exclude on).
            _freshness_boost_enabled = True
            _freshness_exclude_deprecated = True
            _freshness_exclude_expired = True
            _freshness_stale_threshold_days: int | None = None
            if rag_profile is not None:
                _fp_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
                _freshness_boost_enabled = _fp_cfg.freshness_boost_enabled
                _freshness_exclude_deprecated = _fp_cfg.exclude_deprecated_docs
                _freshness_exclude_expired = _fp_cfg.exclude_expired_docs
                _freshness_stale_threshold_days = _fp_cfg.stale_threshold_days

            freshness_filter_enabled = (
                _freshness_boost_enabled
                or _freshness_exclude_deprecated
                or _freshness_exclude_expired
            )
            if freshness_filter_enabled and retrieved_chunks:
                _unique_doc_ids = list({chunk.document_id for chunk in retrieved_chunks})
                _trust_docs = await _document_repository_for_trust.get_documents_by_ids_for_trust(
                    db_session,
                    document_ids=_unique_doc_ids,
                    organization_id=organization_id,
                )
                _freshness_trust_map = _source_freshness_service.build_trust_map(_trust_docs)

                if _freshness_exclude_deprecated or _freshness_exclude_expired:
                    _filter_result = _source_freshness_service.filter_excluded(
                        chunk_document_ids=[str(c.document_id) for c in retrieved_chunks],
                        trust_map=_freshness_trust_map,
                        exclude_deprecated=_freshness_exclude_deprecated,
                        exclude_expired=_freshness_exclude_expired,
                        org_stale_threshold_days=_freshness_stale_threshold_days,
                    )
                    freshness_excluded_count = _filter_result.excluded_count
                    _freshness_stale_ids = _filter_result.stale_document_ids
                    freshness_stale_count = len(_freshness_stale_ids)
                    if _filter_result.excluded_document_ids:
                        _pre_exclusion_chunks = retrieved_chunks
                        _after_exclusion = [
                            c
                            for c in retrieved_chunks
                            if str(c.document_id) not in _filter_result.excluded_document_ids
                        ]
                        # F311: if exclusion empties the context, fall back to
                        # using excluded chunks with a warning.
                        retrieved_chunks, freshness_all_excluded_fallback = (
                            _source_freshness_service.apply_exclusion_fallback(
                                after_filter=_after_exclusion,
                                before_filter=_pre_exclusion_chunks,
                                excluded_ids=_filter_result.excluded_document_ids,
                            )
                        )

                if _freshness_boost_enabled and _freshness_trust_map:
                    adjusted: list[RetrievedChunk] = []
                    for _chunk in retrieved_chunks:
                        _new_score = _source_freshness_service.apply_trust_score_multiplier(
                            score=_chunk.similarity_score,
                            document_id=str(_chunk.document_id),
                            trust_map=_freshness_trust_map,
                            org_stale_threshold_days=_freshness_stale_threshold_days,
                        )
                        if _new_score != _chunk.similarity_score:
                            freshness_boosted_count += 1
                        adjusted.append(
                            RetrievedChunk(
                                document_id=_chunk.document_id,
                                chunk_id=_chunk.chunk_id,
                                filename=_chunk.filename,
                                page_number=_chunk.page_number,
                                text=_chunk.text,
                                similarity_score=_new_score,
                                original_rank=_chunk.original_rank,
                                rerank_score=_chunk.rerank_score,
                                rerank_rank=_chunk.rerank_rank,
                                final_rank=_chunk.final_rank,
                                retrieval_source=_chunk.retrieval_source,
                                graph_score=_chunk.graph_score,
                                graph_hops=_chunk.graph_hops,
                                keyword_score=_chunk.keyword_score,
                                hybrid_score=_chunk.hybrid_score,
                                chunk_type=_chunk.chunk_type,
                                chunk_level=_chunk.chunk_level,
                                parent_text=_chunk.parent_text,
                            )
                        )
                    retrieved_chunks = sorted(
                        adjusted, key=lambda c: c.similarity_score, reverse=True
                    )

            # Table-aware retrieval boost (F298).
            # Applied after freshness scoring, before reranking.
            if settings.feature_enable_table_aware_retrieval and retrieved_chunks:
                _table_boost_enabled = True
                _table_boost_multiplier = settings.table_retrieval_boost_multiplier
                if rag_profile is not None:
                    _tb_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
                    _table_boost_enabled = _tb_cfg.table_retrieval_boost_enabled
                    _table_boost_multiplier = _tb_cfg.table_retrieval_boost_multiplier
                table_boost_enabled = _table_boost_enabled
                retrieved_chunks, _table_boost_result = _table_retrieval_service.apply_table_boost(
                    chunks=retrieved_chunks,
                    query=payload.question,
                    boost_multiplier=_table_boost_multiplier,
                    enabled=_table_boost_enabled,
                )
                if _table_boost_result is not None:
                    table_boost_applied = _table_boost_result.boost_applied
                    table_boost_count = _table_boost_result.boosted_count
                    table_chunk_count = _table_boost_result.table_chunk_count
                    from app.domains.chat.services.table_retrieval_service import (
                        is_table_query as _is_table_query,
                    )

                    table_query_detected = _is_table_query(payload.question)
                    if table_boost_applied:
                        retrieved_chunks = sorted(
                            retrieved_chunks, key=lambda c: c.similarity_score, reverse=True
                        )

            # OCR quality downranking (F299).
            # Loads OCR quality status for retrieved documents and applies score penalties
            # for low/failed OCR quality, ensuring high-quality text chunks rank higher.
            if settings.feature_enable_ocr_quality_downranking and retrieved_chunks:
                ocr_quality_downranking_enabled = True
                _ocr_doc_ids = list({chunk.document_id for chunk in retrieved_chunks})
                _ocr_docs = await _document_repository_for_trust.get_documents_by_ids_for_trust(
                    db_session,
                    document_ids=_ocr_doc_ids,
                    organization_id=organization_id,
                )
                _ocr_quality_map = _ocr_quality_service.build_quality_map(_ocr_docs)
                if _ocr_quality_map:
                    ocr_adjusted: list[RetrievedChunk] = []
                    for _chunk in retrieved_chunks:
                        _new_score = _ocr_quality_service.apply_quality_score(
                            score=_chunk.similarity_score,
                            document_id=str(_chunk.document_id),
                            quality_map=_ocr_quality_map,
                        )
                        if _ocr_quality_service.is_low_confidence(
                            _ocr_quality_map.get(str(_chunk.document_id))
                        ):
                            ocr_low_confidence_chunk_count += 1
                        ocr_adjusted.append(
                            RetrievedChunk(
                                document_id=_chunk.document_id,
                                chunk_id=_chunk.chunk_id,
                                filename=_chunk.filename,
                                page_number=_chunk.page_number,
                                text=_chunk.text,
                                similarity_score=_new_score,
                                original_rank=_chunk.original_rank,
                                rerank_score=_chunk.rerank_score,
                                rerank_rank=_chunk.rerank_rank,
                                final_rank=_chunk.final_rank,
                                retrieval_source=_chunk.retrieval_source,
                                graph_score=_chunk.graph_score,
                                graph_hops=_chunk.graph_hops,
                                keyword_score=_chunk.keyword_score,
                                hybrid_score=_chunk.hybrid_score,
                                chunk_type=_chunk.chunk_type,
                                chunk_level=_chunk.chunk_level,
                                parent_text=_chunk.parent_text,
                            )
                        )
                    retrieved_chunks = sorted(
                        ocr_adjusted, key=lambda c: c.similarity_score, reverse=True
                    )

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

        # Strict context packing (F340).
        # Runs after reranking on selected_chunks.  Applies a composite priority score
        # (trust-weighted similarity + rerank blend + type bonuses), enforces rejection
        # rules for low-relevance, weak-OCR, and stale/superseded chunks, and imposes a
        # global token budget.  The pack is controlled by the RAG profile; the system
        # flag feature_enable_context_packing must also be True.
        if settings.feature_enable_context_packing and selected_chunks:
            _cp_cfg = ContextPackerConfig(enabled=True)
            if rag_profile is not None:
                _cp_rag = RagProfileConfig.model_validate(dict(rag_profile.config))
                _cp_cfg = ContextPackerConfig(
                    enabled=_cp_rag.context_packing_enabled,
                    strategy=_cp_rag.context_packing_strategy,
                    budget_max_tokens=_cp_rag.context_budget_max_tokens,
                    min_relevance_score=_cp_rag.context_min_relevance_score,
                    reject_weak_ocr=_cp_rag.context_reject_weak_ocr,
                    reject_stale_superseded=_cp_rag.context_reject_stale_superseded,
                    require_citations=_cp_rag.context_require_citations,
                    not_found_min_chunks=_cp_rag.context_not_found_min_chunks,
                )
            # Build a freshness state map from the trust data already loaded.
            _cp_freshness_state_map: dict[str, str] = {}
            if _freshness_trust_map:
                for _doc_id, _td in _freshness_trust_map.items():
                    _cp_freshness_state_map[_doc_id] = (
                        _source_freshness_service.derive_freshness_state(
                            _td,
                            org_stale_threshold_days=_freshness_stale_threshold_days,
                        )
                    )
            _context_pack_result = _context_packer_service.pack(
                chunks=selected_chunks,
                config=_cp_cfg,
                ocr_quality_map=_ocr_quality_map if _ocr_quality_map else None,
                freshness_state_map=_cp_freshness_state_map if _cp_freshness_state_map else None,
            )
            context_packing_rejected_count = len(_context_pack_result.rejected)
            if _context_pack_result.selected is not selected_chunks:
                selected_chunks = _context_pack_result.selected
            if context_packing_rejected_count:
                log_query_event(
                    event="query.context_packing.applied",
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    job_id=str(chat_session.id),
                    strategy=_cp_cfg.strategy,
                    selected_count=len(selected_chunks),
                    rejected_count=context_packing_rejected_count,
                    rejected_low_relevance=_context_pack_result.rejected_low_relevance,
                    rejected_weak_ocr=_context_pack_result.rejected_weak_ocr,
                    rejected_stale_superseded=_context_pack_result.rejected_stale_superseded,
                    rejected_token_budget=_context_pack_result.rejected_token_budget,
                    total_estimated_tokens=_context_pack_result.total_estimated_tokens,
                    budget_applied=_context_pack_result.budget_applied,
                )

        confidence_signals = _to_confidence_signals(
            chunks=selected_chunks, rerank_applied=rerank_applied
        )
        _pre_freshness_multiplier = _compute_freshness_multiplier(
            freshness_stale_count, len(selected_chunks)
        )
        confidence_result = _confidence_service.score(
            chunks=confidence_signals,
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=False,
            freshness_multiplier=_pre_freshness_multiplier,
        )
        confidence_score = confidence_result.score
        confidence_category = confidence_result.category
        confidence_explanation = confidence_result.explanation
        _min_chunks_for_answer = (
            _context_pack_result.not_found_min_chunks if _context_pack_result is not None else 1
        )
        not_found = (
            len(selected_chunks) < _min_chunks_for_answer
            or confidence_score < settings.confidence_not_found_threshold
        )

        if not_found:
            confidence_result = _confidence_service.score(
                chunks=confidence_signals,
                citation_count=0,
                citation_validation_score=1.0,
                not_found_signal=True,
                freshness_multiplier=_pre_freshness_multiplier,
            )
            confidence_score = confidence_result.score
            confidence_category = confidence_result.category
            confidence_explanation = confidence_result.explanation

        # Parent-context expansion (F300).
        # Runs on the final selected_chunks after reranking.  For each child chunk that
        # carries a parent_text, the parent section is substituted into the LLM prompt
        # while citations continue to reference the precise child chunk.  Token budget is
        # enforced per chunk; permission safety is guaranteed by org-scoped retrieval.
        if settings.feature_enable_parent_context_expansion and selected_chunks:
            _pc_enabled = True
            _pc_max_tokens = settings.parent_context_max_tokens_per_chunk
            if rag_profile is not None:
                _pc_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
                _pc_enabled = _pc_cfg.parent_context_expansion_enabled
                _pc_max_tokens = _pc_cfg.parent_context_max_tokens_per_chunk
            _parent_expansion_result = _parent_context_expansion_service.expand(
                chunks=selected_chunks,
                enabled=_pc_enabled,
                max_tokens_per_chunk=_pc_max_tokens,
            )
            _parent_context_map = _parent_expansion_result.context_map
            parent_context_expansion_enabled = _parent_expansion_result.expanded_count > 0
            parent_context_child_hit_count = _parent_expansion_result.child_hit_count
            parent_context_expanded_count = _parent_expansion_result.expanded_count
            parent_context_tokens_used = _parent_expansion_result.tokens_used
            if parent_context_expansion_enabled:
                log_query_event(
                    event="query.parent_context.expanded",
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    job_id=str(chat_session.id),
                    child_hit_count=parent_context_child_hit_count,
                    expanded_count=parent_context_expanded_count,
                    tokens_used=parent_context_tokens_used,
                )

        if selected_chunks and not not_found:
            _conflict_enabled = settings.feature_enable_conflict_detection
            _conflict_min_docs = settings.conflict_detection_min_source_docs
            if rag_profile is not None:
                _conflict_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
                _conflict_enabled = _conflict_cfg.conflict_detection_enabled
            conflict_detection_enabled = _conflict_enabled
            if _conflict_enabled:
                _conflict_started = perf_counter()
                conflict_detection_result = await _conflict_detection_service.detect(
                    chunks=_build_conflict_detection_chunks(
                        chunks=selected_chunks,
                        parent_context_map=_parent_context_map if _parent_context_map else None,
                        trust_map=_freshness_trust_map,
                        org_stale_threshold_days=_freshness_stale_threshold_days,
                    ),
                    min_source_docs=_conflict_min_docs,
                )
                conflict_detection_applied = conflict_detection_result.applied
                conflict_detection_latency_ms = int((perf_counter() - _conflict_started) * 1000)
                latencies_ms["conflict_detection"] = conflict_detection_latency_ms
                if conflict_detection_applied:
                    log_query_event(
                        event="query.conflict_detection.completed",
                        organization_id=principal.organization_id,
                        user_id=principal.user_id,
                        job_id=str(chat_session.id),
                        agreement_level=conflict_detection_result.agreement_level,
                        conflict_detected=conflict_detection_result.conflict_detected,
                        conflict_count=len(conflict_detection_result.conflict_pairs),
                        preferred_document_ids=conflict_detection_result.preferred_document_ids,
                        conflicting_document_ids=conflict_detection_result.conflicting_document_ids,
                        latency_ms=conflict_detection_latency_ms,
                    )

        prompt_started = perf_counter()
        prompt = (
            _build_prompt(
                question=payload.question,
                chunks=selected_chunks,
                parent_context_map=_parent_context_map if _parent_context_map else None,
                conflict_context=_build_conflict_context(conflict_detection_result),
                answer_language=answer_language_used,
                template=answer_prompt_template,
            )
            if not not_found
            else ""
        )
        latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

        citation_result: CitationBuildResult | None = None
        if not not_found:
            _tree_search_enabled = await _resolve_tree_search_reasoning_enabled(
                db_session, organization_id=organization_id
            )
            _tree_search_applicable = (
                _tree_search_enabled
                and planner_result is not None
                and planner_result.high_risk
                and len(selected_chunks) >= settings.tree_search_min_context_chunks
            )
            if _tree_search_applicable:
                _tree_search_context_chunks = [
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
                ]
                _tree_search_result = await _tree_search_service.generate_candidates(
                    question=payload.question,
                    context_chunks=_tree_search_context_chunks,
                    not_found_answer=_NOT_FOUND_ANSWER,
                    conflict_context=_build_conflict_context(conflict_detection_result),
                    answer_language=answer_language_used,
                    resolved_profile=chat_profile,
                    max_candidates=settings.tree_search_max_candidates,
                    timeout_seconds=settings.tree_search_timeout_seconds,
                    max_total_tokens=settings.tree_search_max_total_tokens,
                    max_total_cost_usd=Decimal(str(settings.tree_search_max_total_cost_usd)),
                )
                latencies_ms["tree_search"] = _tree_search_result.latency_ms
                if _tree_search_result.candidate_count > 0:
                    _tree_search_candidate_scores: list[TreeSearchCandidateScore] = []
                    _tree_search_evaluations: list[
                        tuple[
                            TreeSearchCandidateScore,
                            CitationBuildResult,
                            list[ChatCitationResponse],
                            LLMAnswerResult,
                        ]
                    ] = []
                    _tree_search_context_signals = confidence_signals
                    _tree_search_min_selected_score = settings.tree_search_min_selected_score
                    for _candidate in _tree_search_result.candidates:
                        _candidate_citation_result = _citation_service.build_citations(
                            not_found=False,
                            answer=_candidate.llm_result.answer,
                            retrieved_chunks=_tree_search_context_chunks,
                            model_citations=_candidate.llm_result.citations,
                        )
                        _candidate_citations: list[ChatCitationResponse] = []
                        for _citation in _candidate_citation_result.citations:
                            _candidate_citations.append(
                                _with_conflict_status(
                                    _with_ocr_quality(
                                        _with_freshness(
                                            _citation,
                                            _freshness_trust_map,
                                            _freshness_stale_ids,
                                        ),
                                        {str(k): v for k, v in _ocr_quality_map.items()},
                                    ),
                                    conflict_detection_result,
                                )
                            )
                        _candidate_score = _tree_search_service.score_candidate(
                            candidate=_candidate,
                            citations=_candidate_citations,
                            confidence_signals=_tree_search_context_signals,
                            citation_validation_score=_candidate_citation_result.validation_score,
                            freshness_multiplier=_compute_freshness_multiplier(
                                freshness_stale_count, len(_candidate_citations)
                            ),
                            ocr_quality_multiplier=_compute_ocr_quality_multiplier(
                                _candidate_citations
                            ),
                            conflict_multiplier=_compute_conflict_multiplier(
                                conflict_detection_result
                            ),
                            table_quality_multiplier=1.0,
                            extraction_quality_multiplier=1.0,
                            graph_context_used=graph_context_result.graph_context_used,
                        )
                        _tree_search_candidate_scores.append(_candidate_score)
                        _tree_search_evaluations.append(
                            (
                                _candidate_score,
                                _candidate_citation_result,
                                _candidate_citations,
                                _candidate.llm_result,
                            )
                        )

                    _tree_search_selection = _tree_search_service.select_candidate(
                        _tree_search_candidate_scores,
                        min_selected_score=_tree_search_min_selected_score,
                    )
                    if _tree_search_selection.selected_candidate is not None:
                        _selected_candidate_score = _tree_search_selection.selected_candidate
                        _selected_evaluation = next(
                            (
                                evaluation
                                for evaluation in _tree_search_evaluations
                                if evaluation[0].strategy == _selected_candidate_score.strategy
                            ),
                            None,
                        )
                        if _selected_evaluation is None and _tree_search_evaluations:
                            _selected_evaluation = _tree_search_evaluations[0]
                        if _selected_evaluation is not None and _tree_search_selection.accepted:
                            (
                                _selected_candidate_score,
                                _selected_citation_result,
                                _selected_candidate_citations,
                                llm_result,
                            ) = _selected_evaluation
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
                            citation_result = _selected_citation_result
                            citations = _selected_candidate_citations
                            citation_validation_failed = citation_result.invalid_chunk_id_count > 0
                            log_query_event(
                                event="query.citations.validated",
                                organization_id=principal.organization_id,
                                user_id=principal.user_id,
                                job_id=str(chat_session.id),
                                validation_score=citation_result.validation_score,
                                model_citation_count=citation_result.model_citation_count,
                                accepted_model_citation_count=(
                                    citation_result.accepted_model_citation_count
                                ),
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
                        elif _selected_evaluation is not None:
                            llm_result = LLMAnswerResult(
                                answer="",
                                not_found=True,
                                citations=[],
                                model_name=_selected_evaluation[3].model_name,
                                prompt_tokens=_selected_evaluation[3].prompt_tokens,
                                completion_tokens=_selected_evaluation[3].completion_tokens,
                                total_tokens=_selected_evaluation[3].total_tokens,
                                approximate_cost_usd=_selected_evaluation[3].approximate_cost_usd,
                                latency_ms=_selected_evaluation[3].latency_ms,
                                retry_count=_selected_evaluation[3].retry_count,
                                used_fallback_parser=_selected_evaluation[3].used_fallback_parser,
                                provider_key=_selected_evaluation[3].provider_key,
                                fallback_used=_selected_evaluation[3].fallback_used,
                                fallback_from=_selected_evaluation[3].fallback_from,
                                fallback_to=_selected_evaluation[3].fallback_to,
                                fallback_reason=_selected_evaluation[3].fallback_reason,
                            )
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
                            answer = _NOT_FOUND_ANSWER
                            not_found = True
                            citations = []
                            citation_result = CitationBuildResult(
                                citations=[],
                                model_citation_count=0,
                                accepted_model_citation_count=0,
                                used_fallback=False,
                                validation_score=1.0,
                                invalid_chunk_id_count=0,
                                metadata_mismatch_count=0,
                                snippet_mismatch_count=0,
                            )

            if citation_result is None:
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
                if citation_result is None:
                    citation_result = CitationBuildResult(
                        citations=[],
                        model_citation_count=0,
                        accepted_model_citation_count=0,
                        used_fallback=False,
                        validation_score=1.0,
                        invalid_chunk_id_count=0,
                        metadata_mismatch_count=0,
                        snippet_mismatch_count=0,
                    )
                citation_chunk_ids = [
                    chunk_id
                    for citation in citation_result.citations
                    if (chunk_id := _parse_uuid_or_none(citation.chunk_id)) is not None
                ]
                provenance_by_chunk_id = await _source_provenance_service.load_citation_details(
                    db_session,
                    organization_id=organization_id,
                    chunk_ids=citation_chunk_ids,
                )
                # Table metadata lookup (F298): fetch table_metadata for any table chunks.
                _citation_chunk_ids = citation_chunk_ids
                _table_metadata_by_chunk_id = (
                    await _document_repository_for_trust.get_chunks_table_metadata(
                        db_session,
                        chunk_ids=_citation_chunk_ids,
                        organization_id=organization_id,
                    )
                )
                _table_metadata_map = {str(k): v for k, v in _table_metadata_by_chunk_id.items()}
                # F315 — build extraction quality map from already-loaded document objects.
                # _ocr_docs contains Document ORM objects with extraction_snapshot and status.
                _extraction_quality_map: dict[str, tuple[str | None, float | None, str]] = {
                    str(doc.id): (
                        (doc.extraction_snapshot or {}).get("document_profile"),
                        (doc.extraction_snapshot or {}).get("extraction_confidence"),
                        doc.status,
                    )
                    for doc in _ocr_docs
                }
                citations = []
                for citation in citation_result.citations:
                    citation_uuid = _parse_uuid_or_none(citation.chunk_id)
                    citations.append(
                        _with_extraction_quality(
                            _with_conflict_status(
                                _with_ocr_quality(
                                    _with_table_metadata(
                                        _with_freshness(
                                            _with_provenance(
                                                citation,
                                                provenance_by_chunk_id.get(citation_uuid),
                                            ),
                                            _freshness_trust_map,
                                            _freshness_stale_ids,
                                        ),
                                        _table_metadata_map,
                                    ),
                                    {str(k): v for k, v in _ocr_quality_map.items()},
                                ),
                                conflict_detection_result,
                            ),
                            _extraction_quality_map,
                        )
                    )
                citation_validation_failed = citation_result.invalid_chunk_id_count > 0
                # F311: compute per-freshness-state citation counts from annotated citations.
                freshness_unreviewed_count = sum(
                    1 for c in citations if getattr(c, "doc_unreviewed_warning", False)
                )
                freshness_deprecated_count = sum(
                    1 for c in citations if getattr(c, "doc_deprecated_warning", False)
                )
                freshness_draft_count = sum(
                    1 for c in citations if getattr(c, "doc_draft_warning", False)
                )
                _freshness_multiplier = _compute_freshness_multiplier(
                    freshness_stale_count, len(citations)
                )
                _ocr_quality_multiplier = _compute_ocr_quality_multiplier(citations)
                _conflict_multiplier = _compute_conflict_multiplier(conflict_detection_result)
                # F315 — evidence quality multipliers
                _table_quality_multiplier = _compute_table_quality_multiplier(citations)
                _extraction_quality_multiplier = _compute_extraction_quality_multiplier(citations)
                confidence_result = _confidence_service.score(
                    chunks=confidence_signals,
                    citation_count=len(citations),
                    citation_validation_score=citation_result.validation_score,
                    not_found_signal=False,
                    freshness_multiplier=_freshness_multiplier,
                    ocr_quality_multiplier=_ocr_quality_multiplier,
                    conflict_multiplier=_conflict_multiplier,
                    table_quality_multiplier=_table_quality_multiplier,
                    extraction_quality_multiplier=_extraction_quality_multiplier,
                    graph_context_used=graph_context_result.graph_context_used,
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

                # Grounded-answer verification (F296/F309).
                # Verifies each factual claim against retrieved chunks plus validated
                # citation evidence. Strict mode refuses answers when evidence is
                # insufficient, even if some claims were rewritten away.
                _gv_enabled, _gv_mode, _gv_threshold = _resolve_grounded_verification_controls(
                    effective_policy=_ai_effective_policy,
                    rag_profile=RagProfileConfig.model_validate(dict(rag_profile.config))
                    if rag_profile is not None
                    else None,
                )
                grounded_verification_enabled = _gv_enabled
                grounded_verification_mode = _gv_mode
                grounded_verification_threshold = _gv_threshold
                if _gv_enabled:
                    _gv_started = perf_counter()
                    grounded_verifier_result = await _grounded_verifier.verify(
                        answer=answer,
                        chunks=[
                            VerifierChunk(
                                chunk_id=str(chunk.chunk_id),
                                text=chunk.text,
                                similarity_score=chunk.similarity_score,
                            )
                            for chunk in selected_chunks
                        ],
                        citations=_build_verifier_citations(citations),
                        mode=_gv_mode,
                        threshold=_gv_threshold,
                    )
                    latencies_ms["grounded_verification"] = int(
                        (perf_counter() - _gv_started) * 1000
                    )
                    if grounded_verifier_result.applied:
                        answer = grounded_verifier_result.final_answer
                        if not answer.strip():
                            not_found = True
                            verification_failed = True
                        elif (
                            _gv_mode == "strict"
                            and grounded_verifier_result.verification_score < _gv_threshold
                        ):
                            not_found = True
                            verification_failed = True
                        elif (
                            _gv_mode == "strict"
                            and grounded_verifier_result.conflicting_claim_count > 0
                        ):
                            # Conflicting sources in strict mode: refuse the answer rather than
                            # showing content that sources actively contradict.
                            not_found = True
                            verification_failed = True
                        elif (
                            grounded_verifier_result.unsupported_claim_count > 0
                            or grounded_verifier_result.conflicting_claim_count > 0
                        ):
                            verification_failed = True
                        if not_found:
                            answer = _NOT_FOUND_ANSWER
                        log_query_event(
                            event="query.grounded_verification.completed",
                            organization_id=principal.organization_id,
                            user_id=principal.user_id,
                            job_id=str(chat_session.id),
                            verdict=grounded_verifier_result.verdict,
                            verification_score=grounded_verifier_result.verification_score,
                            claim_count=grounded_verifier_result.claim_count,
                            supported_count=grounded_verifier_result.supported_claim_count,
                            partial_count=grounded_verifier_result.partially_supported_claim_count,
                            unsupported_count=grounded_verifier_result.unsupported_claim_count,
                            unverifiable_count=grounded_verifier_result.unverifiable_claim_count,
                            removed_count=len(grounded_verifier_result.removed_claims),
                            mode=_gv_mode,
                            threshold=_gv_threshold,
                            latency_ms=grounded_verifier_result.latency_ms,
                        )
                        if verification_failed:
                            log_query_event(
                                event="query.grounded_verification.failed",
                                organization_id=principal.organization_id,
                                user_id=principal.user_id,
                                job_id=str(chat_session.id),
                                verdict=grounded_verifier_result.verdict,
                                removed_count=len(grounded_verifier_result.removed_claims),
                                reason_codes=grounded_verifier_result.reason_codes,
                                mode=_gv_mode,
                                threshold=_gv_threshold,
                            )
                        elif citations:
                            confidence_result = _confidence_service.score(
                                chunks=confidence_signals,
                                citation_count=len(citations),
                                citation_validation_score=citation_result.validation_score,
                                citation_support_score_override=grounded_verifier_result.aggregate_support_score,
                                not_found_signal=False,
                                freshness_multiplier=_freshness_multiplier,
                                ocr_quality_multiplier=_ocr_quality_multiplier,
                                conflict_multiplier=_conflict_multiplier,
                                graph_context_used=graph_context_result.graph_context_used,
                                verification_support_score=grounded_verifier_result.aggregate_support_score,
                            )
                            confidence_score = confidence_result.score
                            confidence_category = confidence_result.category
                            confidence_explanation = confidence_result.explanation

            if not_found:
                confidence_result = _confidence_service.score(
                    chunks=confidence_signals,
                    citation_count=0,
                    citation_validation_score=1.0,
                    not_found_signal=True,
                    freshness_multiplier=_freshness_multiplier,
                    ocr_quality_multiplier=_ocr_quality_multiplier,
                    conflict_multiplier=_conflict_multiplier,
                )
                confidence_score = confidence_result.score
                confidence_category = confidence_result.category
                confidence_explanation = confidence_result.explanation

        # Critic: aggregate quality signals (F339).
        # Runs when the planner flagged a high-risk question (or mode=always).
        # Always synchronous — no LLM call in the critic itself.
        if _pcr_enabled and planner_result is not None and not injection_check.blocked:
            _run_critic = _pcr_mode == "always" or (
                _pcr_mode == "high_risk_only" and planner_result.high_risk
            )
            if _run_critic:
                _gv_r = grounded_verifier_result
                _ev_quality = _build_evidence_quality_inputs(citations)
                critic_result = _answer_critic.evaluate(
                    not_found=not_found,
                    selected_chunk_count=len(selected_chunks),
                    citation_count=len(citations),
                    gv_applied=bool(_gv_r and _gv_r.applied),
                    gv_unsupported_count=(_gv_r.unsupported_claim_count if _gv_r else 0),
                    gv_conflicting_count=(_gv_r.conflicting_claim_count if _gv_r else 0),
                    gv_not_enough_evidence_count=(
                        _gv_r.not_enough_evidence_claim_count if _gv_r else 0
                    ),
                    conflict_detected=conflict_detection_result.conflict_detected,
                    freshness_stale_count=freshness_stale_count,
                    freshness_excluded_count=freshness_excluded_count,
                    freshness_all_excluded_fallback=freshness_all_excluded_fallback,
                    ocr_low_confidence_chunk_count=ocr_low_confidence_chunk_count,
                    table_low_confidence_count=_ev_quality["table_low_confidence_count"],
                    extraction_warning_count=_ev_quality["extraction_warning_count"],
                )
                log_query_event(
                    event="query.planner_critic.evaluated",
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    job_id=str(chat_session.id),
                    strategy=planner_result.strategy,
                    high_risk=planner_result.high_risk,
                    critic_severity=critic_result.severity,
                    warning_count=len(critic_result.warnings),
                    requires_refiner=critic_result.requires_refiner,
                )

                # Refiner: rewrite the answer when critic finds medium/high severity (F339).
                if critic_result.requires_refiner and not not_found and answer.strip():
                    _refiner_snippets = [
                        c.text_snippet for c in citations if getattr(c, "text_snippet", None)
                    ][:10]
                    _refiner_started = perf_counter()
                    refiner_result = await _answer_refiner.refine(
                        draft_answer=answer,
                        critic_instruction=critic_result.refiner_instruction,
                        citation_snippets=_refiner_snippets,
                    )
                    latencies_ms["refiner"] = int((perf_counter() - _refiner_started) * 1000)
                    if refiner_result.applied:
                        _refined = refiner_result.refined_answer.strip()
                        if not _refined:
                            answer = _NOT_FOUND_ANSWER
                            not_found = True
                            verification_failed = True
                        else:
                            answer = _refined
                            if refiner_result.draft_changed:
                                verification_failed = True
                        log_query_event(
                            event="query.planner_critic.refined",
                            organization_id=principal.organization_id,
                            user_id=principal.user_id,
                            job_id=str(chat_session.id),
                            draft_changed=refiner_result.draft_changed,
                            unsupported_removed=refiner_result.unsupported_claims_removed,
                            latency_ms=refiner_result.latency_ms,
                        )

    latencies_ms["llm"] = llm_latency_ms

    # AI response policy post-generation check (F268) — citation, confidence, stale sources.
    # Only run when the pre-generation check did not already block the response.
    if not _ai_pre_result.blocked and not injection_check.blocked:
        _ai_post_result = _ai_policy_engine.evaluate_post_generation(
            confidence_score=confidence_score,
            citation_count=len(citations),
            stale_source_count=freshness_stale_count,
            not_found=not_found,
            effective_policy=_ai_effective_policy,
        )
        if _ai_post_result.blocked:
            _ai_policy_result = _ai_post_result
            answer = _ai_post_result.refusal_message or _NOT_FOUND_ANSWER
            not_found = True
            citations = []
            log_query_event(
                event="query.rejected.policy_post_generation",
                organization_id=principal.organization_id,
                user_id=principal.user_id,
                job_id=str(chat_session.id),
                status_code=status.HTTP_200_OK,
                violated_rules=_ai_post_result.violated_rules,
            )
        elif _ai_post_result.warned:
            _ai_policy_result = _ai_post_result

    # Apply disclaimer to the answer when policy is active and answer is not blocked.
    if not not_found and _ai_effective_policy.source != "none":
        answer = _ai_policy_engine.apply_disclaimer(answer, _ai_policy_result)

    answer_latency_ms = int((perf_counter() - total_started) * 1000)
    rerank_diagnostics = rerank_result.diagnostics if rerank_result is not None else None
    retrieval_diagnostics_payload = _build_retrieval_diagnostics_payload(
        request_id=request_id,
        rag_profile=rag_profile,
        rag_profile_source=rag_profile_source,
        payload=payload,
        source_scope_result=source_scope_result,
        retrieved_chunks=retrieved_chunks,
        selected_chunks=selected_chunks,
        rerank_applied=rerank_applied,
        rerank_diagnostics=rerank_diagnostics,
        parallel_result=parallel_result,
        hybrid_retrieval_enabled=hybrid_retrieval_enabled,
        hybrid_vector_hit_count=hybrid_vector_hit_count,
        hybrid_keyword_hit_count=hybrid_keyword_hit_count,
        query_rewrite_result=query_rewrite_result,
        graph_context_result=graph_context_result,
        document_ids=document_ids,
        final_top_k=final_top_k,
    )

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

        trust_metadata = _build_trust_metadata(
            organization_id=organization_id,
            message_id=str(assistant_message.id),
            question=payload.question,
            query_rewrite_preview_enabled=query_rewrite_preview_enabled,
            not_found=not_found,
            citation_validation_failed=citation_validation_failed,
            verification_failed=verification_failed,
            confidence_score=confidence_score,
            confidence_category=confidence_category,
            confidence_explanation=confidence_explanation,
            citations=citations,
            retrieval_diagnostics_payload=retrieval_diagnostics_payload,
            retrieved_chunks=retrieved_chunks,
            selected_chunks=selected_chunks,
            rerank_applied=rerank_applied,
            rerank_diagnostics=rerank_diagnostics,
            hybrid_vector_hit_count=hybrid_vector_hit_count,
            hybrid_keyword_hit_count=hybrid_keyword_hit_count,
            query_rewrite_result=query_rewrite_result,
            parent_context_expanded_count=parent_context_expanded_count,
            graph_context_result=graph_context_result,
            freshness_excluded_count=freshness_excluded_count,
            freshness_boosted_count=freshness_boosted_count,
            freshness_stale_count=freshness_stale_count,
            freshness_unreviewed_count=freshness_unreviewed_count,
            freshness_deprecated_count=freshness_deprecated_count,
            freshness_draft_count=freshness_draft_count,
            freshness_all_excluded_fallback=freshness_all_excluded_fallback,
            grounded_verifier_result=grounded_verifier_result,
            answer_mode_result=answer_mode_result,
            llm_model=llm_model,
            llm_provider=llm_provider,
            embedding_model=embedding_model,
            llm_fallback_used=llm_fallback_used,
            llm_fallback_from=llm_fallback_from,
            llm_fallback_to=llm_fallback_to,
            llm_fallback_reason=llm_fallback_reason,
            answer_prompt_version=answer_prompt_version,
            conflict_detection_result=conflict_detection_result,
            ai_policy_applied=_ai_effective_policy.source != "none",
            ai_policy_result=_ai_policy_result,
            generated_at=assistant_message.created_at,
            planner_result=planner_result,
            critic_result=critic_result,
            refiner_result=refiner_result,
            route_result=_route_result,
            orchestration_result=_orchestration_result,
        )
        assistant_message.trust_metadata_json = trust_metadata.model_dump(mode="json")
        db_session.add(assistant_message)
        await db_session.flush()

        response_citations = await persist_answer_citations(
            db_session,
            chat_message_id=assistant_message.id,
            citations=citations,
            rerank_applied=rerank_applied,
            repository=chat_repository,
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
                "graph_relation_types_used": _list_or_empty(
                    graph_context_result.graph_relation_types_used
                ),
                "conflict_detection_enabled": conflict_detection_enabled,
                "conflict_detection_applied": conflict_detection_applied,
                "conflict_detection_latency_ms": conflict_detection_latency_ms,
                "conflict_detection_agreement_level": conflict_detection_result.agreement_level,
                "conflict_detection_conflict_count": len(conflict_detection_result.conflict_pairs),
                "conflict_detection_conflicting_document_ids": _list_or_empty(
                    conflict_detection_result.conflicting_document_ids
                ),
                "conflict_detection_preferred_document_ids": _list_or_empty(
                    conflict_detection_result.preferred_document_ids
                ),
                "rerank_applied": rerank_applied,
                "rerank_enabled": rerank_settings.enabled,
                "rerank_provider": rerank_diagnostics.provider_key if rerank_diagnostics else None,
                "rerank_model": rerank_diagnostics.model_name if rerank_diagnostics else None,
                "rerank_fallback_used": rerank_diagnostics.fallback_used
                if rerank_diagnostics
                else False,
                "rerank_fallback_reason": rerank_diagnostics.fallback_reason
                if rerank_diagnostics
                else None,
                "rerank_input_count": rerank_diagnostics.requested_count
                if rerank_diagnostics
                else 0,
                "rerank_batch_count": rerank_diagnostics.batch_count if rerank_diagnostics else 0,
                "rerank_prompt_tokens": rerank_diagnostics.prompt_tokens
                if rerank_diagnostics
                else 0,
                "rerank_completion_tokens": rerank_diagnostics.completion_tokens
                if rerank_diagnostics
                else 0,
                "rerank_total_tokens": rerank_diagnostics.total_tokens if rerank_diagnostics else 0,
                "rerank_cost_usd": _decimal_to_float_or_none(
                    rerank_diagnostics.approximate_cost_usd
                )
                if rerank_diagnostics
                else None,
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
                "conflict_detection_enabled": conflict_detection_enabled,
                "conflict_detection_applied": conflict_detection_applied,
                "conflict_detection_agreement_level": conflict_detection_result.agreement_level,
                "conflict_detection_conflict_count": len(conflict_detection_result.conflict_pairs),
                "conflict_detection_latency_ms": conflict_detection_latency_ms,
                "conflict_detection_conflicting_document_ids": _list_or_empty(
                    conflict_detection_result.conflicting_document_ids
                ),
                "conflict_detection_preferred_document_ids": _list_or_empty(
                    conflict_detection_result.preferred_document_ids
                ),
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

        # Persist policy evaluation log for audit / observability (F268).
        if _ai_effective_policy.source != "none":
            await _ai_policy_repo.create_eval_log(
                db_session,
                organization_id=organization_id,
                user_id=user_id,
                org_policy_id=UUID(_ai_effective_policy.policy_id)
                if _ai_effective_policy.policy_id
                else None,
                collection_id=_ai_policy_collection_id,
                chat_session_id=chat_session.id,
                chat_message_id=assistant_message.id,
                outcome=_ai_policy_result.outcome,
                policy_source=_ai_policy_result.policy_source,
                violated_rules=_ai_policy_result.violated_rules,
                warning_flags=_ai_policy_result.warning_flags,
                question_preview=payload.question[:256],
                confidence_score=confidence_score,
                citation_count=len(citations),
                stale_source_count=freshness_stale_count,
                is_preview_run=False,
            )

        await record_chat_usage(db_session, organization_id=organization_id)
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
            rerank_fallback_reason=rerank_diagnostics.fallback_reason
            if rerank_diagnostics
            else None,
            rerank_input_count=rerank_diagnostics.requested_count if rerank_diagnostics else 0,
            rerank_batch_count=rerank_diagnostics.batch_count if rerank_diagnostics else 0,
            rerank_prompt_tokens=rerank_diagnostics.prompt_tokens if rerank_diagnostics else 0,
            rerank_completion_tokens=rerank_diagnostics.completion_tokens
            if rerank_diagnostics
            else 0,
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
        citations=[] if not_found else response_citations,
        citation_validation_failed=citation_validation_failed,
        verification_failed=verification_failed,
        agreement_level=conflict_detection_result.agreement_level,
        conflict_detected=conflict_detection_result.conflict_detected,
        conflict_summary=(
            conflict_detection_result.conflict_summary
            if conflict_detection_result.conflict_detected
            else None
        ),
        conflicting_document_ids=_list_or_empty(conflict_detection_result.conflicting_document_ids),
        preferred_document_ids=_list_or_empty(conflict_detection_result.preferred_document_ids),
        conflict_pairs=[
            ChatConflictPairResponse(
                document_id_a=pair.document_id_a,
                document_id_b=pair.document_id_b,
                topic=pair.topic,
                severity=pair.severity,
            )
            for pair in conflict_detection_result.conflict_pairs
        ],
        source_freshness_warning=any(
            citation.doc_stale_warning
            or citation.doc_expired_warning
            or citation.doc_is_excluded_status
            for citation in citations
        ),
        source_freshness_warning_reason=(
            "One or more citations come from stale, expired, or archived sources."
            if any(
                citation.doc_stale_warning
                or citation.doc_expired_warning
                or citation.doc_is_excluded_status
                for citation in citations
            )
            else None
        ),
        policy_applied=_ai_effective_policy.source != "none",
        policy_outcome=_ai_policy_result.outcome if _ai_effective_policy.source != "none" else None,
        policy_violated_rules=_ai_policy_result.violated_rules,
        policy_warning_flags=_ai_policy_result.warning_flags,
        policy_disclaimer=_ai_policy_result.disclaimer_text
        if not _ai_policy_result.blocked
        else None,
        trust_metadata=trust_metadata,
        debug=ChatDebugResponse(
            latencies_ms=latencies_ms,
            **retrieval_diagnostics_payload,
            source_scope=source_scope_result.label,
            rerank_enabled=rerank_settings.enabled,
            rerank_input_count=rerank_diagnostics.requested_count if rerank_diagnostics else 0,
            rerank_batch_count=rerank_diagnostics.batch_count if rerank_diagnostics else 0,
            rerank_prompt_tokens=rerank_diagnostics.prompt_tokens if rerank_diagnostics else 0,
            rerank_completion_tokens=rerank_diagnostics.completion_tokens
            if rerank_diagnostics
            else 0,
            rerank_total_tokens=rerank_diagnostics.total_tokens if rerank_diagnostics else 0,
            rerank_cost_usd=_decimal_to_float_or_none(rerank_diagnostics.approximate_cost_usd)
            if rerank_diagnostics
            else None,
            graph_context_enabled=graph_context_result.graph_context_enabled,
            graph_context_used=graph_context_result.graph_context_used,
            graph_context_unavailable=graph_context_result.graph_context_unavailable,
            graph_context_reason=graph_context_result.graph_context_reason,
            graph_seed_entity_count=graph_context_result.graph_seed_entity_count,
            graph_related_entity_count=graph_context_result.graph_related_entity_count,
            graph_chunk_count=graph_context_result.graph_chunk_count,
            graph_max_hops_used=graph_context_result.graph_max_hops_used,
            conflict_detection_enabled=conflict_detection_enabled,
            conflict_detection_applied=conflict_detection_applied,
            conflict_detection_latency_ms=conflict_detection_latency_ms,
            conflict_detection_agreement_level=conflict_detection_result.agreement_level,
            conflict_detection_conflict_count=len(conflict_detection_result.conflict_pairs),
            conflict_detection_conflicting_document_ids=list(
                conflict_detection_result.conflicting_document_ids
            ),
            conflict_detection_preferred_document_ids=list(
                conflict_detection_result.preferred_document_ids
            ),
            conflict_detection_model=conflict_detection_result.model_name or None,
            conflict_detection_provider=conflict_detection_result.provider_key or None,
            graph_relation_types_used=_list_or_empty(
                graph_context_result.graph_relation_types_used
            ),
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
            query_rewriting_enabled=settings.feature_enable_query_rewriting,
            query_rewriting_applied=query_rewrite_result.rewriting_applied
            if query_rewrite_result is not None
            else False,
            query_decomposed=query_rewrite_result.decomposition_applied
            if query_rewrite_result is not None
            else False,
            original_query=query_rewrite_result.original_query
            if query_rewrite_result is not None
            else None,
            rewritten_query=query_rewrite_result.primary_query
            if query_rewrite_result is not None and query_rewrite_result.rewriting_applied
            else None,
            sub_queries=list(query_rewrite_result.sub_queries)
            if query_rewrite_result is not None
            else [],
            query_rewriting_strategy=query_rewrite_result.strategy
            if query_rewrite_result is not None
            else None,
            query_rewriting_latency_ms=query_rewrite_result.latency_ms
            if query_rewrite_result is not None
            else 0,
            grounded_verification_enabled=grounded_verification_enabled,
            grounded_verification_applied=grounded_verifier_result.applied
            if grounded_verifier_result is not None
            else False,
            grounded_verification_verdict=grounded_verifier_result.verdict
            if grounded_verifier_result is not None and grounded_verifier_result.applied
            else None,
            grounded_verification_score=grounded_verifier_result.verification_score
            if grounded_verifier_result is not None and grounded_verifier_result.applied
            else None,
            grounded_verification_claim_count=grounded_verifier_result.claim_count
            if grounded_verifier_result is not None
            else 0,
            grounded_verification_supported_count=grounded_verifier_result.supported_claim_count
            if grounded_verifier_result is not None
            else 0,
            grounded_verification_partially_supported_count=grounded_verifier_result.partially_supported_claim_count
            if grounded_verifier_result is not None
            else 0,
            grounded_verification_unsupported_count=grounded_verifier_result.unsupported_claim_count
            if grounded_verifier_result is not None
            else 0,
            grounded_verification_unverifiable_count=grounded_verifier_result.unverifiable_claim_count
            if grounded_verifier_result is not None
            else 0,
            grounded_verification_conflicting_count=grounded_verifier_result.conflicting_claim_count
            if grounded_verifier_result is not None
            else 0,
            grounded_verification_not_enough_evidence_count=grounded_verifier_result.not_enough_evidence_claim_count
            if grounded_verifier_result is not None
            else 0,
            grounded_verification_removed_count=len(grounded_verifier_result.removed_claims)
            if grounded_verifier_result is not None
            else 0,
            grounded_verification_reason_codes=list(grounded_verifier_result.reason_codes)
            if grounded_verifier_result is not None
            else [],
            grounded_verification_mode=grounded_verifier_result.mode
            if grounded_verifier_result is not None
            else grounded_verification_mode,
            grounded_verification_threshold=grounded_verifier_result.threshold
            if grounded_verifier_result is not None
            else grounded_verification_threshold,
            grounded_verification_model=grounded_verifier_result.model_name
            if grounded_verifier_result is not None and grounded_verifier_result.applied
            else None,
            grounded_verification_latency_ms=grounded_verifier_result.latency_ms
            if grounded_verifier_result is not None
            else 0,
            freshness_filter_enabled=freshness_filter_enabled,
            freshness_excluded_count=freshness_excluded_count,
            freshness_boosted_count=freshness_boosted_count,
            freshness_stale_count=freshness_stale_count,
            freshness_unreviewed_count=freshness_unreviewed_count,
            freshness_deprecated_count=freshness_deprecated_count,
            freshness_draft_count=freshness_draft_count,
            freshness_all_excluded_fallback=freshness_all_excluded_fallback,
            table_boost_enabled=table_boost_enabled,
            table_boost_applied=table_boost_applied,
            table_boost_count=table_boost_count,
            table_chunk_count=table_chunk_count,
            table_query_detected=table_query_detected,
            ocr_quality_downranking_enabled=ocr_quality_downranking_enabled,
            ocr_low_confidence_chunk_count=ocr_low_confidence_chunk_count,
            parent_context_expansion_enabled=parent_context_expansion_enabled,
            parent_context_child_hit_count=parent_context_child_hit_count,
            parent_context_expanded_count=parent_context_expanded_count,
            parent_context_tokens_used=parent_context_tokens_used,
        ),
        created_at=assistant_message.created_at,
    )


@router.get(
    "/messages/{message_id}/trust-metadata",
    response_model=AnswerTrustMetadataResponse,
    summary="Get answer trust metadata for a saved message",
    description=(
        "Returns the versioned trust metadata snapshot for a saved assistant message. "
        "Available after chat completion. Never returns raw prompts, chain-of-thought, "
        "ACL snapshots, or internal UUIDs. Organization-scoped and user-filtered."
    ),
)
async def get_message_trust_metadata(
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
) -> AnswerTrustMetadataResponse:
    user_id, organization_id = _principal_user_and_org(principal)

    try:
        message_uuid = UUID(message_id)
    except ValueError as exc:
        raise _safe_http_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="message_not_found",
            message="Message not found",
        ) from exc

    message = await chat_repository.get_message_for_user(
        db_session,
        message_id=message_uuid,
        organization_id=organization_id,
        user_id=user_id,
    )
    if message is None or message.role != ChatRole.assistant.value:
        raise _safe_http_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="message_not_found",
            message="Message not found",
        )

    if message.trust_metadata_json is None:
        raise _safe_http_error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="trust_metadata_not_available",
            message="Trust metadata is not available for this message",
        )

    return AnswerTrustMetadataResponse.model_validate(message.trust_metadata_json)


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


@router.post("/sessions/{session_id}/messages", response_model=ChatMessageResponse, deprecated=True)
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

    # Shared views have never carried source provenance; keep that (no ``decorate``).
    shared_citations = await load_message_citations(
        db_session,
        messages=messages_orm,
        organization_id=organization_id,
        repository=chat_repository,
    )
    items = [
        ChatSessionMessageResponse(
            message_id=str(message.id),
            role=message.role,
            content=message.content,
            confidence_score=message.confidence_score,
            confidence_category=_confidence_category_from_score(message.confidence_score),
            citations=shared_citations.get(message.id, []),
            created_at=message.created_at,
        )
        for message in messages_orm
    ]

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
    from app.domains.feedback_review.schemas.review import normalize_feedback_category
    from app.models.message_feedback import MessageFeedback as _MessageFeedback  # noqa: F401

    return MessageFeedbackResponse(
        feedback_id=str(fb.id),
        message_id=str(fb.message_id),
        user_id=str(fb.user_id),
        rating=fb.rating,  # type: ignore[arg-type]
        reason=fb.reason,  # type: ignore[arg-type]
        comment=fb.comment,
        category=normalize_feedback_category(fb.category),  # type: ignore[arg-type]
        question_text=fb.question_text,
        answer_text=fb.answer_text,
        model_name=fb.model_name,
        llm_provider=(
            fb.trust_metadata_json.get("llm_provider")
            if isinstance(fb.trust_metadata_json, dict)
            else None
        ),
        rag_profile_id=str(fb.rag_profile_id) if fb.rag_profile_id else None,
        retain_until=fb.retain_until,
        redacted_at=fb.redacted_at,
        converted_to_eval_question_id=str(fb.converted_to_eval_question_id)
        if fb.converted_to_eval_question_id
        else None,
        trust_metadata=fb.trust_metadata_json if isinstance(fb.trust_metadata_json, dict) else None,
        trace_id=getattr(fb, "trace_id", None),
        selected_citation_ids=getattr(fb, "selected_citation_ids", None),
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

    diag = payload.diagnostics
    rag_profile_uuid: UUID | None = None
    if diag and diag.rag_profile_id:
        try:
            rag_profile_uuid = UUID(diag.rag_profile_id)
        except ValueError:
            rag_profile_uuid = None

    feedback = await feedback_repository.upsert_feedback(
        db_session,
        message_id=msg_id,
        user_id=user_id,
        organization_id=organization_id,
        rating=payload.rating,
        reason=payload.reason,
        comment=payload.comment,
        category=payload.category,
        question_text=diag.question_text if diag else None,
        answer_text=diag.answer_text if diag else None,
        citations_json={"items": diag.citations} if diag and diag.citations is not None else None,
        retrieval_diagnostics_json=diag.retrieval_diagnostics if diag else None,
        model_name=diag.model_name if diag else None,
        rag_profile_id=rag_profile_uuid,
        trust_metadata_json=(
            {
                **(diag.trust_metadata or {}),
                **(
                    {"llm_provider": diag.llm_provider}
                    if diag and diag.llm_provider is not None
                    else {}
                ),
            }
            if diag
            else None
        ),
        trace_id=diag.trace_id if diag else None,
        selected_citation_ids=diag.selected_citation_ids if diag else None,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="chat.message.feedback.submitted",
        resource_type="chat_message",
        resource_id=msg_id,
        request_id=request_id,
        metadata={
            "rating": payload.rating,
            "reason": payload.reason,
            "category": payload.category,
            "has_diagnostics": diag is not None,
        },
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

    # Activity timeline helpers — step_seq is the display order in the UI.
    _activity_step_seq = 0

    # Planner-critic-refiner pipeline state (F339)
    _ws_planner_result: PlannerResult | None = None
    _ws_critic_result: CriticResult | None = None
    _ws_refiner_result: RefinerResult | None = None
    _ws_route_result: RetrievalRouteResult | None = None
    _ws_orchestration_result: ToolOrchestrationResult | None = None
    _ws_pcr_enabled: bool = False
    _ws_pcr_mode: str = "high_risk_only"
    _ws_pcr_high_risk: frozenset[str] = frozenset()
    _ws_routing_enabled: bool = False

    async def send_step(
        step_key: str,
        label: str,
        state: str,
        detail: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        nonlocal _activity_step_seq
        if state in ("running", "pending"):
            _activity_step_seq += 1
        await send(
            "activity.step.update",
            {
                "step_key": step_key,
                "sequence": _activity_step_seq,
                "label": label,
                "state": state,
                "detail": detail,
                "duration_ms": duration_ms,
            },
        )

    await send_step("understanding_question", "Understanding your question", "running")

    user_id, organization_id = _principal_user_and_org(principal)
    user_roles = list(principal.roles or [])

    async with SessionLocal() as db_session:
        try:
            # ── Plan quota (parity with POST /chat) ───────────────────────────
            try:
                await ensure_chat_quota(db_session, organization_id=organization_id, transport="ws")
            except HTTPException as exc:
                denial = chat_quota_denial(exc)
                if denial is None:
                    raise
                await send_step("understanding_question", "Understanding your question", "failed")
                await send("chat.error", denial, safe_error_code="plan_limit_exceeded")
                log_query_event(
                    event="query.rejected.quota_exceeded",
                    organization_id=str(organization_id),
                    user_id=str(user_id),
                    transport="ws",
                    request_id=request_id,
                )
                return

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
            document_ids = await _filter_authorized_document_ids_for_chat(
                db_session,
                principal=principal,
                organization_id=organization_id,
                user_id=user_id,
                user_roles=user_roles,
                document_ids=document_ids,
            )
            await send("chat.scope.validated", {"scope_label": source_scope_result.label})
            await send_step("understanding_question", "Understanding your question", "success")
            # Emit planning_answer step when planner is active (F339)
            if _ws_pcr_enabled and _ws_planner_result is not None:
                _strategy_label = STRATEGY_LABELS.get(
                    _ws_planner_result.strategy, _ws_planner_result.strategy
                )
                await send_step(
                    "planning_answer",
                    "Planning answer strategy",
                    "success",
                    detail=_strategy_label,
                )
            # Emit selecting_strategy step when dynamic routing is active (F341)
            if _ws_routing_enabled and _ws_route_result is not None:
                await send_step(
                    "selecting_strategy",
                    "Selecting search strategy",
                    "success",
                    detail=_ws_route_result.method_label,
                )
            # Emit tool_orchestration step when adaptive tool orchestration is active (F342)
            if (
                settings.feature_enable_chat_tool_orchestration
                and _ws_orchestration_result is not None
            ):
                _orch_detail = (
                    f"{_ws_orchestration_result.authorized_count} of "
                    f"{_ws_orchestration_result.tool_count} tools authorized"
                )
                await send_step(
                    "tool_orchestration",
                    "Orchestrating available tools",
                    "success",
                    detail=_orch_detail,
                )
            await send_step("checking_sources", "Checking accessible sources", "running")

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

            _ai_org_policy = await _ai_policy_repo.get_active(
                db_session, organization_id=organization_id
            )
            _ai_collection_override = None
            _ai_policy_collection_id: UUID | None = None
            if _ai_org_policy is not None and query_request.source_scope is not None:
                try:
                    _ai_policy_collection_id = UUID(str(query_request.source_scope))
                    _ai_collection_override = await _ai_policy_repo.get_collection_override(
                        db_session,
                        org_policy_id=_ai_org_policy.id,
                        collection_id=_ai_policy_collection_id,
                    )
                except (ValueError, AttributeError):
                    pass
            _ai_effective_policy = _ai_policy_engine.resolve(
                _ai_org_policy, _ai_collection_override
            )
            _ai_pre_result = _ai_policy_engine.evaluate_pre_generation(
                query_request.question, _ai_effective_policy
            )
            _ai_policy_result: AiPolicyEvaluationResult = AiPolicyEvaluationResult()
            if _ai_pre_result.blocked and not injection_check.blocked:
                _ai_policy_result = _ai_pre_result
            answer_mode_result = _answer_mode_service.classify(question=query_request.question)
            scope_inventory_requested = _is_scope_inventory_question(query_request.question)
            if answer_mode_result.mode == "grounded" and not scope_inventory_requested:
                answer_prompt_version = await _resolve_answer_prompt_version(
                    db_session, organization_id=organization_id
                )
                answer_prompt_template = answer_prompt_version.content

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
            not_found = injection_check.blocked or _ai_pre_result.blocked
            citation_validation_failed = False
            verification_failed = False
            grounded_verifier_result: GroundedVerifierResult | None = None
            graph_context_result = GraphRetrievalResult()
            parallel_result: ParallelRetrievalResult | None = None
            rerank_result: RerankResult | None = None
            query_rewrite_result: QueryRewritingResult | None = None
            query_rewrite_preview_enabled = settings.feature_enable_query_rewrite_preview
            hybrid_retrieval_enabled = False
            hybrid_vector_hit_count = 0
            hybrid_keyword_hit_count = 0
            freshness_excluded_count = 0
            freshness_boosted_count = 0
            freshness_stale_count = 0
            freshness_unreviewed_count = 0
            freshness_deprecated_count = 0
            freshness_draft_count = 0
            freshness_all_excluded_fallback = False
            parent_context_expanded_count = 0
            conflict_detection_enabled = False
            conflict_detection_applied = False
            conflict_detection_latency_ms = 0
            conflict_detection_result = ConflictDetectionResult(
                conflict_detected=False,
                agreement_level="full",
            )
            final_top_k = query_request.top_k or settings.retrieval_final_top_k
            rerank_applied = False

            chat_profile = await resolve_task_profile(
                db_session, organization_id=organization_id, task_type=TaskType.chat
            )
            rag_profile, rag_profile_source = await resolve_profile_for_context(
                db_session,
                organization_id=organization_id,
                collection_id=None,
            )
            rerank_settings = _build_rerank_settings(
                dict(rag_profile.config) if rag_profile is not None else None
            )

            # Planner: classify question strategy (F339) — keyword heuristics, <1 ms.
            # Also runs when dynamic routing is enabled (F341).
            _ws_pcr_enabled, _ws_pcr_mode, _ws_pcr_high_risk = _resolve_planner_critic_controls(
                RagProfileConfig.model_validate(dict(rag_profile.config))
                if rag_profile is not None
                else None,
            )
            _ws_routing_enabled = settings.feature_enable_dynamic_retrieval_routing
            if (
                (_ws_pcr_enabled or _ws_routing_enabled)
                and not injection_check.blocked
                and not not_found
                and answer_mode_result.mode == "grounded"
                and not scope_inventory_requested
            ):
                _ws_planner_result = _answer_planner.classify(
                    question=query_request.question,
                    graph_context_available=settings.feature_enable_graph_rag,
                    connector_search_scope=False,
                    high_risk_strategies_override=_ws_pcr_high_risk,
                )

            # Dynamic retrieval strategy routing (F341).
            if (
                _ws_routing_enabled
                and not injection_check.blocked
                and not not_found
                and answer_mode_result.mode == "grounded"
                and not scope_inventory_requested
            ):
                _ws_profile_cfg = (
                    RagProfileConfig.model_validate(dict(rag_profile.config))
                    if rag_profile is not None
                    else None
                )
                _ws_route_result = _retrieval_strategy_router.route(
                    planner_strategy=(
                        _ws_planner_result.strategy
                        if _ws_planner_result is not None
                        else "standard"
                    ),
                    features=FeatureAvailability(
                        hybrid_retrieval_enabled=settings.feature_enable_hybrid_retrieval,
                        graph_rag_enabled=settings.feature_enable_graph_rag,
                        parent_context_expansion_enabled=(
                            settings.feature_enable_parent_context_expansion
                        ),
                        keyword_retrieval_enabled=settings.feature_enable_hybrid_retrieval,
                    ),
                    profile_override=(
                        _ws_profile_cfg.retrieval_strategy_override
                        if _ws_profile_cfg is not None
                        else None
                    ),
                    request_override=query_request.retrieval_strategy_override,
                    allow_user_override=settings.feature_enable_retrieval_strategy_user_override,
                )

            # Adaptive tool orchestration (F342): authorize pipeline tools for this query.
            if (
                settings.feature_enable_chat_tool_orchestration
                and not injection_check.blocked
                and not not_found
                and answer_mode_result.mode == "grounded"
                and not scope_inventory_requested
            ):
                _ws_orchestration_feature_availability: dict[str, bool] = {
                    "feature_enable_connectors": settings.feature_enable_connectors,
                    "feature_enable_graph_rag": settings.feature_enable_graph_rag,
                }
                _ws_orchestration_overrides = await _chat_tool_policy_repo.list_by_organization(
                    db_session, organization_id=organization_id
                )
                _ws_orchestration_disabled: frozenset[str] = frozenset(
                    o.tool_name for o in _ws_orchestration_overrides if not o.enabled
                )
                _ws_orchestration_result = _chat_tool_orchestrator.orchestrate(
                    planner_strategy=(
                        _ws_planner_result.strategy
                        if _ws_planner_result is not None
                        else "standard"
                    ),
                    principal=principal,
                    feature_availability=_ws_orchestration_feature_availability,
                    disabled_tool_names=_ws_orchestration_disabled,
                    source_scope_mode=query_request.scope_mode,
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
                await send_step(
                    "checking_sources",
                    "Checking accessible sources",
                    "failed",
                    detail="Request could not be processed",
                )
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

            elif scope_inventory_requested:
                # Scope inventory questions are answered from indexed document metadata
                # and first chunks; vector retrieval and LLM generation are unnecessary.
                embedding_model = None
                retrieve_started = perf_counter()
                inventory_result = await _build_scope_inventory_result(
                    db_session,
                    principal=principal,
                    organization_id=organization_id,
                    user_id=user_id,
                    user_roles=user_roles,
                    document_ids=document_ids,
                )
                latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)
                retrieved_chunks = inventory_result.retrieved_chunks
                selected_chunks = inventory_result.retrieved_chunks
                citations = inventory_result.citations
                answer = _build_scope_inventory_answer(
                    inventory=inventory_result,
                    source_scope_result=source_scope_result,
                )
                not_found = inventory_result.total_count == 0
                await send_step(
                    "checking_sources",
                    "Checking accessible sources",
                    "warning" if not_found else "success",
                    detail=(
                        "No indexed files found"
                        if not_found
                        else f"Found {inventory_result.total_count} indexed file"
                        f"{'s' if inventory_result.total_count != 1 else ''}"
                    ),
                )
                await send("retrieval.started")
                await send("retrieval.completed", {"chunk_count": len(retrieved_chunks)})
                await send_step(
                    "searching_documents",
                    "Searching knowledge base",
                    "warning" if not_found else "success",
                    detail=(
                        "No indexed files found"
                        if not_found
                        else f"Included {inventory_result.total_count} indexed file"
                        f"{'s' if inventory_result.total_count != 1 else ''}"
                    ),
                    duration_ms=latencies_ms["retrieve"],
                )
                await send_step("reranking_evidence", "Ranking evidence by relevance", "skipped")
                await send("generation.started")
                await send_step("drafting_answer", "Drafting answer", "running")
                await send("generation.delta", {"text": answer})
                await send_step(
                    "drafting_answer",
                    "Drafting answer",
                    "warning" if not_found else "success",
                    detail="No indexed files found" if not_found else None,
                )
                await send("citation.validation.completed", {"citation_count": len(citations)})
                if citations:
                    await send_step(
                        "verifying_citations",
                        "Verifying source citations",
                        "success",
                        detail=f"Linked {len(citations)} citation"
                        f"{'s' if len(citations) != 1 else ''}",
                    )
                confidence_signals = _to_confidence_signals(
                    chunks=selected_chunks,
                    rerank_applied=False,
                )
                confidence_result = _confidence_service.score(
                    chunks=confidence_signals,
                    citation_count=len(citations),
                    citation_validation_score=1.0,
                    not_found_signal=not_found,
                )
                confidence_score = confidence_result.score
                confidence_category = confidence_result.category
                confidence_explanation = confidence_result.explanation

            elif answer_mode_result.mode == "guidance":
                # ── Guidance mode (no retrieval) ─────────────────────────────
                await send_step("checking_sources", "Checking accessible sources", "skipped")
                await send_step("searching_documents", "Searching knowledge base", "skipped")
                embedding_model = None
                prompt = _prompt_service.build_guidance_prompt(
                    question=query_request.question, answer_language=answer_language_used
                )
                await send("generation.started")
                await send_step("drafting_answer", "Drafting answer", "running")
                try:
                    llm_result = await _llm_service.generate_answer(
                        prompt=prompt, resolved_profile=chat_profile
                    )
                except (TransientLLMServiceError, PermanentLLMServiceError):
                    await send_step("drafting_answer", "Drafting answer", "failed")
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
                citations = []
                await send("generation.delta", {"text": answer})
                await send_step(
                    "drafting_answer",
                    "Drafting answer",
                    "warning" if not_found else "success",
                    detail="No relevant answer found" if not_found else None,
                    duration_ms=llm_result.latency_ms,
                )
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
                    rerank_settings.max_input_candidates or settings.rerank_default_input_candidates
                )
                retrieval_top_k = max(
                    final_top_k,
                    rerank_input_limit if rerank_applied else final_top_k,
                )

                # Retrieval
                _source_count = len(document_ids) if document_ids is not None else 0
                await send_step(
                    "checking_sources",
                    "Checking accessible sources",
                    "success",
                    detail=f"Searching {_source_count} source{'s' if _source_count != 1 else ''}",
                )
                await send("retrieval.started")
                await send_step("searching_documents", "Searching knowledge base", "running")
                retrieve_started = perf_counter()
                try:
                    graph_enabled = await _resolve_graph_rag_enabled(
                        db_session, organization_id=organization_id
                    )
                    _ws_route_wants_vector_only = (
                        _ws_route_result is not None and _ws_route_result.method == "vector"
                    )
                    _ws_effective_hybrid = (
                        settings.feature_enable_hybrid_retrieval and not _ws_route_wants_vector_only
                    )
                    _ws_parallel_budget = ParallelRetrievalBudget(
                        max_parallel_calls=settings.retrieval_parallel_max_calls,
                        timeout_ms=settings.retrieval_parallel_timeout_ms,
                        max_retry_attempts=settings.retrieval_parallel_max_retry_attempts,
                        max_total_tokens=settings.retrieval_parallel_max_total_tokens,
                        max_total_cost_usd=(
                            None
                            if settings.retrieval_parallel_max_total_cost_usd is None
                            else settings.retrieval_parallel_max_total_cost_usd
                        ),
                    )
                    parallel_result = await _parallel_retrieval_optimizer.execute(
                        session=db_session,
                        organization_id=organization_id,
                        document_ids=document_ids,
                        queries=[query_request.question],
                        query_retrieval_service=_query_retrieval_service,
                        keyword_retrieval_service=_keyword_retrieval_service,
                        graph_retrieval_service=_graph_retrieval_service,
                        graph_enabled=graph_enabled,
                        keyword_enabled=_ws_effective_hybrid,
                        qdrant_client=_get_qdrant_client(),
                        top_k=retrieval_top_k,
                        exact_match_boost=settings.hybrid_retrieval_exact_match_boost,
                        budget=_ws_parallel_budget,
                        index_versions=settings.active_index_versions,
                    )
                    embedding_model = parallel_result.embedding_model or embedding_model
                    embedding_prompt_tokens = parallel_result.total_embedding_prompt_tokens
                    graph_context_result = parallel_result.graph_result
                    _ws_record = (
                        parallel_result.query_records[0] if parallel_result.query_records else None
                    )
                    if _ws_record is not None:
                        retrieved_chunks = [
                            _hybrid_to_retrieved_chunk(c)
                            if _ws_effective_hybrid and _ws_record.keyword_candidates is not None
                            else _to_retrieved_chunk(c)
                            for c in _ws_record.vector_candidates
                        ]
                        if _ws_effective_hybrid and _ws_record.keyword_candidates is not None:
                            hybrid_result = _hybrid_retrieval_service.merge(
                                vector_candidates=_ws_record.vector_candidates,
                                keyword_candidates=_ws_record.keyword_candidates.candidates,
                                exact_match_tokens=_ws_record.keyword_candidates.exact_match_tokens,
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
                        retrieved_chunks = await _source_provenance_service.filter_active_chunks(
                            db_session, organization_id=organization_id, chunks=retrieved_chunks
                        )
                        retrieved_chunks = await filter_chunks_by_cite_access(
                            db_session,
                            principal=principal,
                            organization_id=organization_id,
                            user_id=user_id,
                            user_roles=user_roles,
                            chunks=retrieved_chunks,
                        )
                        retrieved_chunks = _with_original_ranks(retrieved_chunks)
                    else:
                        retrieved_chunks = []
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
                        graph_result=graph_context_result,
                    )
                except Exception:
                    await send("chat.error", safe_error_code="retrieval_failed")
                    return
                latencies_ms["retrieve"] = int((perf_counter() - retrieve_started) * 1000)
                await send(
                    "retrieval.completed",
                    {"chunk_count": len(retrieved_chunks)},
                )
                _retrieve_count = len(retrieved_chunks)
                await send_step(
                    "searching_documents",
                    "Searching knowledge base",
                    "warning" if _retrieve_count == 0 else "success",
                    detail=f"Found {_retrieve_count} relevant passage{'s' if _retrieve_count != 1 else ''}",
                    duration_ms=latencies_ms["retrieve"],
                )

                # Reranking
                rerank_started = perf_counter()
                if rerank_applied:
                    await send("rerank.started")
                    await send_step(
                        "reranking_evidence", "Ranking evidence by relevance", "running"
                    )
                else:
                    await send_step(
                        "reranking_evidence", "Ranking evidence by relevance", "skipped"
                    )
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
                    await send_step(
                        "reranking_evidence",
                        "Ranking evidence by relevance",
                        "success",
                        detail=f"Selected {len(selected_chunks)} top source{'s' if len(selected_chunks) != 1 else ''}",
                        duration_ms=latencies_ms["rerank"],
                    )

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
                _stream_conflict_multiplier: float = 1.0

                if selected_chunks and not not_found:
                    _conflict_enabled = settings.feature_enable_conflict_detection
                    _conflict_min_docs = settings.conflict_detection_min_source_docs
                    if rag_profile is not None:
                        _conflict_cfg = RagProfileConfig.model_validate(dict(rag_profile.config))
                        _conflict_enabled = _conflict_cfg.conflict_detection_enabled
                    conflict_detection_enabled = _conflict_enabled
                    if _conflict_enabled:
                        _conflict_started = perf_counter()
                        conflict_detection_result = await _conflict_detection_service.detect(
                            chunks=_build_conflict_detection_chunks(
                                chunks=selected_chunks,
                                parent_context_map=None,
                                trust_map={},
                                org_stale_threshold_days=None,
                            ),
                            min_source_docs=_conflict_min_docs,
                        )
                        conflict_detection_applied = conflict_detection_result.applied
                        conflict_detection_latency_ms = int(
                            (perf_counter() - _conflict_started) * 1000
                        )
                        latencies_ms["conflict_detection"] = conflict_detection_latency_ms
                        _stream_conflict_multiplier = _compute_conflict_multiplier(
                            conflict_detection_result
                        )
                        if conflict_detection_applied:
                            await send(
                                "conflict_detection.completed",
                                {
                                    "agreement_level": conflict_detection_result.agreement_level,
                                    "conflict_detected": conflict_detection_result.conflict_detected,
                                    "conflict_count": len(conflict_detection_result.conflict_pairs),
                                    "preferred_document_ids": conflict_detection_result.preferred_document_ids,
                                    "conflicting_document_ids": conflict_detection_result.conflicting_document_ids,
                                },
                            )

                prompt_started = perf_counter()
                prompt = (
                    _build_prompt(
                        question=query_request.question,
                        chunks=selected_chunks,
                        conflict_context=_build_conflict_context(conflict_detection_result),
                        answer_language=answer_language_used,
                        template=answer_prompt_template,
                    )
                    if not not_found
                    else ""
                )
                latencies_ms["prompt"] = int((perf_counter() - prompt_started) * 1000)

                if not not_found:
                    await send("generation.started")
                    await send_step("drafting_answer", "Drafting answer", "running")
                    try:
                        llm_result = await _llm_service.generate_answer(
                            prompt=prompt, resolved_profile=chat_profile
                        )
                    except (TransientLLMServiceError, PermanentLLMServiceError):
                        await send_step("drafting_answer", "Drafting answer", "failed")
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
                        await send_step(
                            "drafting_answer",
                            "Drafting answer",
                            "warning",
                            detail="No relevant answer found",
                            duration_ms=llm_latency_ms,
                        )
                    else:
                        await send_step(
                            "drafting_answer",
                            "Drafting answer",
                            "success",
                            duration_ms=llm_latency_ms,
                        )
                        # Citation validation
                        await send("citation.validation.started")
                        await send_step(
                            "verifying_citations", "Verifying source citations", "running"
                        )
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
                        citation_chunk_ids = [
                            chunk_id
                            for c in citation_result.citations
                            if (chunk_id := _parse_uuid_or_none(c.chunk_id)) is not None
                        ]
                        provenance_by_chunk_id = (
                            await _source_provenance_service.load_citation_details(
                                db_session,
                                organization_id=organization_id,
                                chunk_ids=citation_chunk_ids,
                            )
                        )
                        citations = []
                        for citation in citation_result.citations:
                            citation_uuid = _parse_uuid_or_none(citation.chunk_id)
                            citations.append(
                                _with_conflict_status(
                                    _with_provenance(
                                        citation,
                                        provenance_by_chunk_id.get(citation_uuid),
                                    ),
                                    conflict_detection_result,
                                )
                            )
                        citation_validation_failed = citation_result.invalid_chunk_id_count > 0
                        confidence_result = _confidence_service.score(
                            chunks=confidence_signals,
                            citation_count=len(citations),
                            citation_validation_score=citation_result.validation_score,
                            not_found_signal=False,
                            conflict_multiplier=_stream_conflict_multiplier,
                        )
                        confidence_score = confidence_result.score
                        confidence_category = confidence_result.category
                        confidence_explanation = confidence_result.explanation
                        await send(
                            "citation.validation.completed",
                            {"citation_count": len(citations)},
                        )
                        await send_step(
                            "verifying_citations",
                            "Verifying source citations",
                            "warning" if citation_validation_failed else "success",
                            detail=f"Linked {len(citations)} citation{'s' if len(citations) != 1 else ''}",
                        )

                    if not_found:
                        confidence_result = _confidence_service.score(
                            chunks=confidence_signals,
                            citation_count=0,
                            citation_validation_score=1.0,
                            not_found_signal=True,
                            conflict_multiplier=_stream_conflict_multiplier,
                        )
                        confidence_score = confidence_result.score
                        confidence_category = confidence_result.category
                        confidence_explanation = confidence_result.explanation

                # Critic + refiner for high-risk answers (F339 WS pipeline).
                if (
                    _ws_pcr_enabled
                    and _ws_planner_result is not None
                    and not injection_check.blocked
                ):
                    _ws_run_critic = _ws_pcr_mode == "always" or (
                        _ws_pcr_mode == "high_risk_only" and _ws_planner_result.high_risk
                    )
                    if _ws_run_critic:
                        _ws_ev = _build_evidence_quality_inputs(citations)
                        _ws_critic_result = _answer_critic.evaluate(
                            not_found=not_found,
                            selected_chunk_count=len(selected_chunks),
                            citation_count=len(citations),
                            conflict_detected=conflict_detection_result.conflict_detected,
                            freshness_stale_count=freshness_stale_count,
                            freshness_excluded_count=freshness_excluded_count,
                            freshness_all_excluded_fallback=freshness_all_excluded_fallback,
                            table_low_confidence_count=_ws_ev["table_low_confidence_count"],
                            extraction_warning_count=_ws_ev["extraction_warning_count"],
                        )
                        _critic_severity = _ws_critic_result.severity
                        await send_step(
                            "reviewing_answer",
                            "Reviewing answer quality",
                            "warning" if _critic_severity in ("medium", "high") else "success",
                            detail=(
                                f"{len(_ws_critic_result.warnings)} quality warning(s) found"
                                if _ws_critic_result.warnings
                                else "No quality issues found"
                            ),
                        )

                        if _ws_critic_result.requires_refiner and not not_found and answer.strip():
                            await send_step(
                                "refining_answer", "Refining with verified claims", "running"
                            )
                            _ws_refiner_snippets = [
                                c.text_snippet
                                for c in citations
                                if getattr(c, "text_snippet", None)
                            ][:10]
                            _ws_refiner_started = perf_counter()
                            _ws_refiner_result = await _answer_refiner.refine(
                                draft_answer=answer,
                                critic_instruction=_ws_critic_result.refiner_instruction,
                                citation_snippets=_ws_refiner_snippets,
                            )
                            latencies_ms["refiner"] = int(
                                (perf_counter() - _ws_refiner_started) * 1000
                            )
                            if _ws_refiner_result.applied:
                                _ws_refined = _ws_refiner_result.refined_answer.strip()
                                if not _ws_refined:
                                    answer = _NOT_FOUND_ANSWER
                                    not_found = True
                                    verification_failed = True
                                else:
                                    answer = _ws_refined
                                    if _ws_refiner_result.draft_changed:
                                        verification_failed = True
                                await send_step(
                                    "refining_answer",
                                    "Refining with verified claims",
                                    "warning" if not_found else "success",
                                    detail=(
                                        "Unsupported claims removed"
                                        if _ws_refiner_result.draft_changed
                                        else "No changes needed"
                                    ),
                                    duration_ms=_ws_refiner_result.latency_ms,
                                )
                            else:
                                await send_step(
                                    "refining_answer",
                                    "Refining with verified claims",
                                    "skipped",
                                )

            latencies_ms["llm"] = llm_latency_ms
            answer_latency_ms = int((perf_counter() - total_started) * 1000)
            latencies_ms["total"] = answer_latency_ms
            rerank_diagnostics = rerank_result.diagnostics if rerank_result is not None else None
            retrieval_diagnostics_payload = _build_retrieval_diagnostics_payload(
                request_id=request_id,
                rag_profile=rag_profile,
                rag_profile_source=rag_profile_source,
                payload=query_request,
                source_scope_result=source_scope_result,
                retrieved_chunks=retrieved_chunks,
                selected_chunks=selected_chunks,
                rerank_applied=rerank_applied,
                rerank_diagnostics=rerank_diagnostics,
                parallel_result=parallel_result,
                hybrid_retrieval_enabled=hybrid_retrieval_enabled,
                hybrid_vector_hit_count=hybrid_vector_hit_count,
                hybrid_keyword_hit_count=hybrid_keyword_hit_count,
                query_rewrite_result=query_rewrite_result,
                graph_context_result=graph_context_result,
                document_ids=document_ids,
                final_top_k=final_top_k,
            )

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
                await persist_answer_citations(
                    db_session,
                    chat_message_id=assistant_message.id,
                    citations=citations,
                    rerank_applied=rerank_applied,
                    repository=chat_repository,
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
                        "rerank_provider": rerank_diagnostics.provider_key
                        if rerank_diagnostics
                        else None,
                        "rerank_model": rerank_diagnostics.model_name
                        if rerank_diagnostics
                        else None,
                        "rerank_fallback_used": rerank_diagnostics.fallback_used
                        if rerank_diagnostics
                        else False,
                        "rerank_fallback_reason": rerank_diagnostics.fallback_reason
                        if rerank_diagnostics
                        else None,
                        "rerank_input_count": rerank_diagnostics.requested_count
                        if rerank_diagnostics
                        else 0,
                        "rerank_batch_count": rerank_diagnostics.batch_count
                        if rerank_diagnostics
                        else 0,
                        "rerank_prompt_tokens": rerank_diagnostics.prompt_tokens
                        if rerank_diagnostics
                        else 0,
                        "rerank_completion_tokens": rerank_diagnostics.completion_tokens
                        if rerank_diagnostics
                        else 0,
                        "rerank_total_tokens": rerank_diagnostics.total_tokens
                        if rerank_diagnostics
                        else 0,
                        "rerank_cost_usd": _decimal_to_float_or_none(
                            rerank_diagnostics.approximate_cost_usd
                        )
                        if rerank_diagnostics
                        else None,
                        "conflict_detection_enabled": conflict_detection_enabled,
                        "conflict_detection_applied": conflict_detection_applied,
                        "conflict_detection_agreement_level": conflict_detection_result.agreement_level,
                        "conflict_detection_conflict_count": len(
                            conflict_detection_result.conflict_pairs
                        ),
                        "conflict_detection_latency_ms": conflict_detection_latency_ms,
                        "transport": "websocket",
                    },
                )
                await record_chat_usage(db_session, organization_id=organization_id)
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
                        "conflict_detection_enabled": conflict_detection_enabled,
                        "conflict_detection_applied": conflict_detection_applied,
                        "conflict_detection_agreement_level": conflict_detection_result.agreement_level,
                        "conflict_detection_conflict_count": len(
                            conflict_detection_result.conflict_pairs
                        ),
                        "transport": "websocket",
                    },
                )
                trust_metadata = _build_trust_metadata(
                    organization_id=organization_id,
                    message_id=str(assistant_message.id),
                    question=query_request.question,
                    query_rewrite_preview_enabled=query_rewrite_preview_enabled,
                    not_found=not_found,
                    citation_validation_failed=citation_validation_failed,
                    verification_failed=verification_failed,
                    confidence_score=confidence_score,
                    confidence_category=confidence_category,
                    confidence_explanation=confidence_explanation,
                    citations=citations,
                    retrieval_diagnostics_payload=retrieval_diagnostics_payload,
                    retrieved_chunks=retrieved_chunks,
                    selected_chunks=selected_chunks,
                    rerank_applied=rerank_applied,
                    rerank_diagnostics=rerank_diagnostics,
                    hybrid_vector_hit_count=hybrid_vector_hit_count,
                    hybrid_keyword_hit_count=hybrid_keyword_hit_count,
                    query_rewrite_result=query_rewrite_result,
                    parent_context_expanded_count=parent_context_expanded_count,
                    graph_context_result=graph_context_result,
                    freshness_excluded_count=freshness_excluded_count,
                    freshness_boosted_count=freshness_boosted_count,
                    freshness_stale_count=freshness_stale_count,
                    freshness_unreviewed_count=freshness_unreviewed_count,
                    freshness_deprecated_count=freshness_deprecated_count,
                    freshness_draft_count=freshness_draft_count,
                    freshness_all_excluded_fallback=freshness_all_excluded_fallback,
                    grounded_verifier_result=grounded_verifier_result,
                    answer_mode_result=answer_mode_result,
                    llm_model=llm_model,
                    llm_provider=llm_provider,
                    embedding_model=embedding_model,
                    llm_fallback_used=llm_fallback_used,
                    llm_fallback_from=llm_fallback_from,
                    llm_fallback_to=llm_fallback_to,
                    llm_fallback_reason=llm_fallback_reason,
                    answer_prompt_version=answer_prompt_version,
                    conflict_detection_result=conflict_detection_result,
                    ai_policy_applied=_ai_effective_policy.source != "none",
                    ai_policy_result=_ai_policy_result,
                    generated_at=assistant_message.created_at,
                    planner_result=_ws_planner_result,
                    critic_result=_ws_critic_result,
                    refiner_result=_ws_refiner_result,
                    route_result=_ws_route_result,
                    orchestration_result=_ws_orchestration_result,
                )
                assistant_message.trust_metadata_json = trust_metadata.model_dump(mode="json")
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
                    rerank_fallback_used=rerank_diagnostics.fallback_used
                    if rerank_diagnostics
                    else False,
                    rerank_fallback_reason=rerank_diagnostics.fallback_reason
                    if rerank_diagnostics
                    else None,
                    rerank_input_count=rerank_diagnostics.requested_count
                    if rerank_diagnostics
                    else 0,
                    rerank_batch_count=rerank_diagnostics.batch_count if rerank_diagnostics else 0,
                    rerank_prompt_tokens=rerank_diagnostics.prompt_tokens
                    if rerank_diagnostics
                    else 0,
                    rerank_completion_tokens=rerank_diagnostics.completion_tokens
                    if rerank_diagnostics
                    else 0,
                    rerank_total_tokens=rerank_diagnostics.total_tokens
                    if rerank_diagnostics
                    else 0,
                    rerank_cost_usd=rerank_diagnostics.approximate_cost_usd
                    if rerank_diagnostics
                    else None,
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
                    conflict_detection_enabled=conflict_detection_enabled,
                    conflict_detection_applied=conflict_detection_applied,
                    conflict_detection_latency_ms=conflict_detection_latency_ms,
                    conflict_detection_agreement_level=conflict_detection_result.agreement_level,
                    conflict_detection_conflict_count=len(conflict_detection_result.conflict_pairs),
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
                conflict_detection_enabled=conflict_detection_enabled,
                conflict_detection_applied=conflict_detection_applied,
                conflict_detection_agreement_level=conflict_detection_result.agreement_level,
                conflict_detection_conflict_count=len(conflict_detection_result.conflict_pairs),
                transport="websocket",
            )
            await send_step("preparing_final_answer", "Preparing final answer", "success")

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
                agreement_level=conflict_detection_result.agreement_level,
                conflict_detected=conflict_detection_result.conflict_detected,
                conflict_summary=(
                    conflict_detection_result.conflict_summary
                    if conflict_detection_result.conflict_detected
                    else None
                ),
                conflicting_document_ids=_list_or_empty(
                    conflict_detection_result.conflicting_document_ids
                ),
                preferred_document_ids=_list_or_empty(
                    conflict_detection_result.preferred_document_ids
                ),
                conflict_pairs=[
                    ChatConflictPairResponse(
                        document_id_a=pair.document_id_a,
                        document_id_b=pair.document_id_b,
                        topic=pair.topic,
                        severity=pair.severity,
                    )
                    for pair in conflict_detection_result.conflict_pairs
                ],
                debug=ChatDebugResponse(
                    latencies_ms=latencies_ms,
                    **retrieval_diagnostics_payload,
                    source_scope=source_scope_result.label,
                    rerank_enabled=rerank_settings.enabled,
                    rerank_input_count=rerank_diagnostics.requested_count
                    if rerank_diagnostics
                    else 0,
                    rerank_batch_count=rerank_diagnostics.batch_count if rerank_diagnostics else 0,
                    rerank_prompt_tokens=rerank_diagnostics.prompt_tokens
                    if rerank_diagnostics
                    else 0,
                    rerank_completion_tokens=rerank_diagnostics.completion_tokens
                    if rerank_diagnostics
                    else 0,
                    rerank_total_tokens=rerank_diagnostics.total_tokens
                    if rerank_diagnostics
                    else 0,
                    rerank_cost_usd=_decimal_to_float_or_none(
                        rerank_diagnostics.approximate_cost_usd
                    )
                    if rerank_diagnostics
                    else None,
                    graph_context_enabled=graph_context_result.graph_context_enabled,
                    graph_context_used=graph_context_result.graph_context_used,
                    graph_context_unavailable=graph_context_result.graph_context_unavailable,
                    graph_context_reason=graph_context_result.graph_context_reason,
                    graph_seed_entity_count=graph_context_result.graph_seed_entity_count,
                    graph_related_entity_count=graph_context_result.graph_related_entity_count,
                    graph_chunk_count=graph_context_result.graph_chunk_count,
                    graph_max_hops_used=graph_context_result.graph_max_hops_used,
                    conflict_detection_enabled=conflict_detection_enabled,
                    conflict_detection_applied=conflict_detection_applied,
                    conflict_detection_latency_ms=conflict_detection_latency_ms,
                    conflict_detection_agreement_level=conflict_detection_result.agreement_level,
                    conflict_detection_conflict_count=len(conflict_detection_result.conflict_pairs),
                    conflict_detection_conflicting_document_ids=list(
                        conflict_detection_result.conflicting_document_ids
                    ),
                    conflict_detection_preferred_document_ids=list(
                        conflict_detection_result.preferred_document_ids
                    ),
                    conflict_detection_model=conflict_detection_result.model_name or None,
                    conflict_detection_provider=conflict_detection_result.provider_key or None,
                    graph_relation_types_used=_list_or_empty(
                        graph_context_result.graph_relation_types_used
                    ),
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
                trust_metadata=trust_metadata,
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
    ticket: str | None = Query(default=None),
) -> None:
    """WebSocket chat endpoint (F277). Feature-flagged via FEATURE_CHAT_WEBSOCKET_ENABLED.

    Handshake auth (R02-10): ``?ticket=`` from POST /chat/ws-ticket, then an
    ``Authorization`` header, then the deprecated ``?token=``.
    """
    if not settings.feature_chat_websocket_enabled:
        await websocket.close(code=4503, reason="WebSocket chat is not enabled")
        return

    # ── Auth ──────────────────────────────────────────────────────────────────
    async with SessionLocal() as auth_session:
        auth_result = await authenticate_ws_handshake(
            headers=websocket.headers,
            client=websocket.client,
            ticket=ticket,
            token=token,
            db_session=auth_session,
        )

    principal = auth_result.principal
    if principal is None:
        log_query_event(
            event="chat.ws.auth.rejected",
            method=auth_result.method,
            failure=auth_result.failure,
        )
        reason = (
            "Missing auth credentials"
            if auth_result.failure == "missing_credentials"
            else "Unauthorized"
        )
        await websocket.close(code=4401, reason=reason)
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
                outcome = await consume_rate_limit(
                    scope=RateLimitScope.chat, endpoint="/chat/ws", principal=principal
                )
                if outcome.decision == RateLimitDecision.limited:
                    await send_event("chat.error", safe_error_code="rate_limit_exceeded")
                    continue
                if outcome.decision == RateLimitDecision.unavailable:
                    await send_event("chat.error", safe_error_code="rate_limiter_unavailable")
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
    citation_rows = await chat_repository.list_citations_for_message(
        db_session,
        chat_message_id=assistant_msg.id,
    )
    citation_doc_ids = [citation.document_id for citation in citation_rows]
    trust_docs = await _document_repository_for_trust.get_documents_by_ids_for_trust(
        db_session,
        document_ids=citation_doc_ids,
        organization_id=organization_id,
    )
    trust_map = _source_freshness_service.build_trust_map(trust_docs)
    trust_docs_by_id = {str(doc.id): doc for doc in trust_docs}
    safe_citations: list[SharedAnswerCitationResponse] = []
    for citation in citation_rows:
        trust = trust_map.get(str(citation.document_id))
        if trust is not None:
            effective_status = _source_freshness_service.compute_effective_trust_status(trust)
            warning = effective_status in {
                "stale",
                "needs_review",
                "unreviewed",
                "expired",
                "archived",
                "deprecated",
                "superseded",
                "draft",
            }
        else:
            effective_status = None
            warning = False

        source_doc = trust_docs_by_id.get(str(citation.document_id))
        safe_citations.append(
            SharedAnswerCitationResponse(
                document_id=str(citation.document_id),
                chunk_id=str(citation.chunk_id),
                filename=source_doc.filename if source_doc is not None else None,
                page_number=citation.page_number,
                text_snippet=citation.text_snippet,
                source_trust_status=effective_status,
                source_freshness_warning=warning,
                source_freshness_warning_reason=(
                    "Citation comes from a stale, draft, unreviewed, expired, or archived source."
                    if warning
                    else None
                ),
            )
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=viewer_user_id,
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
