import asyncio
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from types import MethodType
from typing import Annotated, Any, Literal, cast
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

from app.auth.authorization_service import AuthorizationService
from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.auth.passwords import (
    PasswordHashConfig,
    build_password_hasher,
    hash_password,
    verify_password,
)
from app.auth.policy_engine import Action
from app.auth.resource_context_builder import (
    build_document_resource_contexts_batch,
    get_subject_accessible_collection_ids,
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
from app.domains.ai.providers.factory import default_provider_factory
from app.domains.ai.providers.protocols import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
)
from app.domains.ai_response_policy.repositories.ai_response_policy import (
    AiResponsePolicyRepository,
)
from app.domains.ai_response_policy.services.policy_engine import (
    AiResponsePolicyEngine,
)
from app.domains.ai_response_policy.services.policy_engine import (
    PolicyEvaluationResult as AiPolicyEvaluationResult,
)
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
    CitationTrustRecord,
    ClaimSupportRecord,
    ConfidenceReasonRecord,
    ConfidenceTrustRecord,
    ConflictStatusRecord,
    EvidenceQualityRecord,
    GroundedVerificationRecord,
    ModelMetadataRecord,
    PolicyEnforcementRecord,
    QueryInterpretationRecord,
    RetrievalDiagnosticsRecord,
    SourceFreshnessRecord,
)
from app.domains.chat.services.citation_service import CitationContextChunk, CitationService
from app.domains.chat.services.confidence_service import ConfidenceChunkSignal, ConfidenceService
from app.domains.chat.services.conflict_detection_service import (
    ConflictDetectionChunk,
    ConflictDetectionResult,
    ConflictDetectionService,
)
from app.domains.chat.services.graph_retrieval_service import (
    GraphRetrievalResult,
    GraphRetrievalService,
    GraphRetrievedChunk,
)
from app.domains.chat.services.grounded_answer_verifier import (
    GroundedAnswerVerifier,
    GroundedVerifierResult,
    VerifierChunk,
    VerifierCitation,
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
from app.domains.chat.services.parent_context_expansion_service import (
    ParentContextExpansionService,
    ParentExpansionResult,
)
from app.domains.chat.services.prompt_service import PromptContextChunk, PromptService
from app.domains.chat.services.query_retrieval_service import (
    QueryRetrievalService,
    RetrievedCandidate,
)
from app.domains.chat.services.query_rewriting_service import (
    QueryRewritingResult,
    QueryRewritingService,
)
from app.domains.chat.services.rerank_service import (
    RerankCandidate,
    RerankResult,
    RerankService,
    RerankSettings,
)
from app.domains.chat.services.source_freshness_service import (
    DocumentTrustData,
    SourceFreshnessService,
)
from app.domains.chat.services.source_scope_service import (
    ResolvedSourceScope,
    SourceScopeService,
)
from app.domains.chat.services.table_retrieval_service import (
    TableBoostResult,
    TableRetrievalService,
)
from app.domains.connectors.services.source_provenance import SourceProvenanceService
from app.domains.documents.repositories.documents import DocumentRepository as _DocumentRepository
from app.domains.documents.services.ocr_quality_service import OcrQualityService
from app.domains.prompt_templates.services.prompt_template_service import PromptTemplateService
from app.domains.prompt_templates.services.rendering import PromptTemplateValidationError
from app.domains.quota.schemas.quota_schemas import QuotaType
from app.domains.quota.services.plan_enforcement_service import plan_enforcement_service
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
_conflict_detection_service = ConflictDetectionService()
_graph_retrieval_service = GraphRetrievalService()
_feature_flag_service = FeatureFlagService()
_openai_client: Any | None = None


class _ChatCompletionProviderProxy:
    async def complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        if _openai_client is None:
            provider = default_provider_factory.get_chat_provider(None)
            return await provider.complete(request)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": f"{request.system_message}\n\n{request.prompt}"},
        ]
        create_kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
        }
        if request.json_mode:
            create_kwargs["response_format"] = {"type": "json_object"}
        if request.max_tokens is not None:
            create_kwargs["max_tokens"] = request.max_tokens

        started = perf_counter()
        response = await _openai_client.chat.completions.create(**create_kwargs)
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        choice = response.choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None) if message is not None else None
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens))
        return ChatCompletionResponse(
            content=str(content or ""),
            model=str(getattr(response, "model", request.model) or request.model),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )


class _EmbeddingProviderProxy:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        if _openai_client is None:
            provider = default_provider_factory.get_embedding_provider()
            return await provider.embed(request)

        started = perf_counter()
        response = await _openai_client.embeddings.create(
            model=request.model,
            input=request.texts,
        )
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        data = getattr(response, "data", []) or []
        vectors = [list(getattr(item, "embedding", []) or []) for item in data]
        usage = getattr(response, "usage", None)
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or prompt_tokens)
        return EmbeddingResponse(
            vectors=vectors,
            model=str(getattr(response, "model", request.model) or request.model),
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )


_llm_service = LLMService(provider=_ChatCompletionProviderProxy())
_injection_guard = PromptInjectionGuard()
_query_rewriting_service = QueryRewritingService()
_grounded_verifier = GroundedAnswerVerifier()
_authorization_service = AuthorizationService()
_source_freshness_service = SourceFreshnessService()
_table_retrieval_service = TableRetrievalService()
_ocr_quality_service = OcrQualityService()
_parent_context_expansion_service = ParentContextExpansionService()
_document_repository_for_trust = _DocumentRepository()
_ai_policy_repo = AiResponsePolicyRepository()
_ai_policy_engine = AiResponsePolicyEngine()
_NOT_FOUND_ANSWER = "I could not find this information in the uploaded documents."
_query_retrieval_service._embedding_provider = _EmbeddingProviderProxy()


def _resolve_chat_embedding_provider(self: QueryRetrievalService):
    if self._embedding_provider is not None:
        return self._embedding_provider
    if _openai_client is not None:
        return _EmbeddingProviderProxy()
    from app.domains.ai.providers.factory import default_provider_factory

    return default_provider_factory.get_embedding_provider()


def _resolve_chat_completion_provider(self: LLMService, provider_key: str | None = None):
    if self._provider is not None:
        return self._provider
    if _openai_client is not None:
        return _ChatCompletionProviderProxy()
    from app.domains.ai.providers.factory import default_provider_factory

    return default_provider_factory.get_chat_provider(provider_key)


def _resolve_grounded_verification_controls(
    *,
    effective_policy: Any,
    rag_profile: RagProfileConfig | None,
) -> tuple[bool, str, float]:
    """Resolve grounded-verification activation and strictness.

    Collection/org policy can elevate verification for sensitive workspaces.
    When no policy override is set, fall back to the RAG profile config.
    """

    enabled = settings.feature_enable_grounded_answer_verification
    mode: str = "standard"
    threshold = 0.7

    if rag_profile is not None:
        enabled = rag_profile.grounded_answer_verification_enabled
        mode = rag_profile.grounded_answer_verification_mode
        threshold = rag_profile.grounded_answer_verification_threshold

    policy_mode = getattr(effective_policy, "grounded_verification_mode", "off")
    if policy_mode != "off":
        enabled = True
        mode = policy_mode
        policy_threshold = getattr(effective_policy, "grounded_verification_threshold", None)
        if policy_threshold is not None:
            threshold = policy_threshold

    return enabled, mode, threshold


def _build_verifier_citations(citations: list[ChatCitationResponse]) -> list[VerifierCitation]:
    verifier_citations: list[VerifierCitation] = []
    for citation in citations:
        if not citation.document_id or not citation.chunk_id:
            continue
        verifier_citations.append(
            VerifierCitation(
                document_id=citation.document_id,
                chunk_id=citation.chunk_id,
                filename=citation.filename or "",
                page_number=citation.page_number,
                text_snippet=(citation.text_snippet or "")[:400],
                score=citation.score or 0.0,
                similarity_score=citation.similarity_score or 0.0,
                rerank_score=citation.rerank_score,
                source_trust_status=citation.source_trust_status,
                doc_ocr_quality_status=citation.doc_ocr_quality_status,
                doc_ocr_low_confidence_warning=citation.doc_ocr_low_confidence_warning,
                doc_stale_warning=citation.doc_stale_warning,
                doc_expired_warning=citation.doc_expired_warning,
                doc_is_excluded_status=citation.doc_is_excluded_status,
            )
        )
    return verifier_citations


def _build_claim_support_records(
    *,
    grounded_verifier_result: GroundedVerifierResult | None,
) -> list[ClaimSupportRecord]:
    if grounded_verifier_result is None:
        return []
    records: list[ClaimSupportRecord] = []
    for claim_index, claim in enumerate(grounded_verifier_result.claims, start=1):
        records.append(
            ClaimSupportRecord(
                claim_index=claim_index,
                claim_text=claim.claim_text,
                support_status=claim.support_status,
                support_score=claim.support_score,
                evidence_match_score=claim.evidence_match_score,
                source_quality_score=claim.source_quality_score,
                rerank_score=claim.rerank_score,
                chunk_coverage_score=claim.chunk_coverage_score,
                citation_indices=list(claim.citation_indices),
            )
        )
    return records


_query_retrieval_service._resolve_embedding_provider = MethodType(
    _resolve_chat_embedding_provider,
    _query_retrieval_service,
)
_llm_service._resolve_provider = MethodType(_resolve_chat_completion_provider, _llm_service)


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
    chunk_type: str = "text"
    # Parent-child context (F300): present when a child chunk was retrieved.
    chunk_level: int = 0
    parent_text: str | None = None


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


def _parse_uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _decimal_to_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _list_or_empty(value: object) -> list[object]:
    if value is None:
        return []
    try:
        return list(value)  # type: ignore[arg-type]
    except TypeError:
        return []


def _to_retrieved_chunk(candidate: RetrievedCandidate) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=candidate.document_id,
        chunk_id=candidate.chunk_id,
        filename=candidate.filename,
        page_number=candidate.page_number,
        text=candidate.text,
        similarity_score=candidate.similarity_score,
        chunk_type=candidate.chunk_type,
        chunk_level=candidate.chunk_level,
        parent_text=candidate.parent_text,
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
        chunk_type=getattr(candidate, "chunk_type", "text"),
        chunk_level=candidate.chunk_level,
        parent_text=candidate.parent_text,
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
            chunk_type=existing.chunk_type,
            chunk_level=existing.chunk_level,
            parent_text=existing.parent_text or chunk.parent_text,
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
                chunk_type=chunk.chunk_type,
                chunk_level=chunk.chunk_level,
                parent_text=chunk.parent_text,
            )
        )
    return ranked_chunks


def _with_freshness(
    citation: ChatCitationResponse,
    trust_map: dict[str, DocumentTrustData],
    stale_document_ids: frozenset[str],
) -> ChatCitationResponse:
    """Annotate a citation with document trust/freshness metadata (F297/F311)."""
    trust = trust_map.get(citation.document_id)
    if trust is None:
        return citation
    effective_status = _source_freshness_service.compute_effective_trust_status(trust)
    freshness_state = _source_freshness_service.derive_freshness_state(trust)
    is_stale = citation.document_id in stale_document_ids or effective_status in {
        "stale",
        "needs_review",
    }
    is_unreviewed = effective_status == "needs_review"
    is_deprecated = effective_status in {"archived", "deprecated", "superseded"}
    is_draft = effective_status == "draft" or trust.quality_state == "draft"
    return ChatCitationResponse(
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=citation.conflict_status,
        doc_trust_status=trust.trust_status,
        doc_quality_state=trust.quality_state,
        doc_review_status=trust.review_status or trust.trust_status,
        doc_review_owner_id=str(trust.review_owner_id) if trust.review_owner_id else None,
        doc_review_due_date=trust.review_due_date,
        doc_expiry_date=trust.expiry_date,
        doc_version_label=trust.version_label,
        doc_review_date=trust.review_date,
        doc_effective_date=trust.effective_date,
        doc_stale_warning=is_stale,
        doc_expired_warning=effective_status == "expired",
        doc_is_excluded_status=effective_status
        in {"archived", "deprecated", "superseded", "expired"},
        freshness_state=freshness_state,
        doc_last_updated_at=trust.last_updated_at,
        doc_unreviewed_warning=is_unreviewed,
        doc_deprecated_warning=is_deprecated,
        doc_draft_warning=is_draft,
    )


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
        conflict_status=citation.conflict_status,
    )


def _with_table_metadata(
    citation: ChatCitationResponse,
    table_metadata_map: dict[str, dict],
) -> ChatCitationResponse:
    """Annotate a citation with table structure metadata when available."""
    meta = table_metadata_map.get(citation.chunk_id)
    if not meta:
        return citation
    raw_conf = meta.get("confidence")
    table_conf: float | None = float(raw_conf) if raw_conf is not None else None
    table_low_conf_warn = table_conf is not None and table_conf < _TABLE_CONFIDENCE_LOW_THRESHOLD
    return ChatCitationResponse(
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=citation.conflict_status,
        doc_trust_status=citation.doc_trust_status,
        doc_version_label=citation.doc_version_label,
        doc_review_date=citation.doc_review_date,
        doc_effective_date=citation.doc_effective_date,
        doc_stale_warning=citation.doc_stale_warning,
        doc_is_excluded_status=citation.doc_is_excluded_status,
        is_table_chunk=True,
        table_caption=meta.get("caption"),
        table_row_count=meta.get("row_count"),
        table_col_count=meta.get("col_count"),
        table_headers=list(meta.get("headers") or []),
        table_section_context=meta.get("section_context"),
        table_extraction_confidence=table_conf,
        table_low_confidence_warning=table_low_conf_warn,
    )


def _with_ocr_quality(
    citation: ChatCitationResponse,
    ocr_quality_map: dict[str, str],
) -> ChatCitationResponse:
    """Annotate a citation with OCR quality status and low-confidence warning."""
    quality_status = ocr_quality_map.get(citation.document_id)
    if quality_status is None:
        return citation
    return ChatCitationResponse(
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=citation.conflict_status,
        doc_trust_status=citation.doc_trust_status,
        doc_review_status=citation.doc_review_status,
        doc_review_owner_id=citation.doc_review_owner_id,
        doc_review_due_date=citation.doc_review_due_date,
        doc_expiry_date=citation.doc_expiry_date,
        doc_version_label=citation.doc_version_label,
        doc_review_date=citation.doc_review_date,
        doc_effective_date=citation.doc_effective_date,
        doc_stale_warning=citation.doc_stale_warning,
        doc_expired_warning=citation.doc_expired_warning,
        doc_is_excluded_status=citation.doc_is_excluded_status,
        freshness_state=citation.freshness_state,
        doc_last_updated_at=citation.doc_last_updated_at,
        doc_unreviewed_warning=citation.doc_unreviewed_warning,
        doc_deprecated_warning=citation.doc_deprecated_warning,
        is_table_chunk=citation.is_table_chunk,
        table_caption=citation.table_caption,
        table_row_count=citation.table_row_count,
        table_col_count=citation.table_col_count,
        table_headers=citation.table_headers,
        table_section_context=citation.table_section_context,
        table_extraction_confidence=citation.table_extraction_confidence,
        table_low_confidence_warning=citation.table_low_confidence_warning,
        doc_ocr_quality_status=quality_status,
        doc_ocr_low_confidence_warning=_ocr_quality_service.is_low_confidence(quality_status),
        doc_extraction_quality=citation.doc_extraction_quality,
        doc_extraction_warning=citation.doc_extraction_warning,
        doc_processing_warning=citation.doc_processing_warning,
    )


def _with_conflict_status(
    citation: ChatCitationResponse,
    conflict_result: ConflictDetectionResult,
) -> ChatCitationResponse:
    if not conflict_result.applied or not conflict_result.conflict_detected:
        return citation

    status: Literal["preferred", "conflicting", "neutral"] = "neutral"
    if citation.document_id in conflict_result.preferred_document_ids:
        status = "preferred"
    elif citation.document_id in conflict_result.conflicting_document_ids:
        status = "conflicting"

    return ChatCitationResponse(
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=status,
        doc_trust_status=citation.doc_trust_status,
        doc_review_status=citation.doc_review_status,
        doc_review_owner_id=citation.doc_review_owner_id,
        doc_review_due_date=citation.doc_review_due_date,
        doc_expiry_date=citation.doc_expiry_date,
        doc_version_label=citation.doc_version_label,
        doc_review_date=citation.doc_review_date,
        doc_effective_date=citation.doc_effective_date,
        doc_stale_warning=citation.doc_stale_warning,
        doc_expired_warning=citation.doc_expired_warning,
        doc_is_excluded_status=citation.doc_is_excluded_status,
        freshness_state=citation.freshness_state,
        doc_last_updated_at=citation.doc_last_updated_at,
        doc_unreviewed_warning=citation.doc_unreviewed_warning,
        doc_deprecated_warning=citation.doc_deprecated_warning,
        is_table_chunk=citation.is_table_chunk,
        table_caption=citation.table_caption,
        table_row_count=citation.table_row_count,
        table_col_count=citation.table_col_count,
        table_headers=citation.table_headers,
        table_section_context=citation.table_section_context,
        table_extraction_confidence=citation.table_extraction_confidence,
        table_low_confidence_warning=citation.table_low_confidence_warning,
        doc_ocr_quality_status=citation.doc_ocr_quality_status,
        doc_ocr_low_confidence_warning=citation.doc_ocr_low_confidence_warning,
        doc_extraction_quality=citation.doc_extraction_quality,
        doc_extraction_warning=citation.doc_extraction_warning,
        doc_processing_warning=citation.doc_processing_warning,
    )


def _with_extraction_quality(
    citation: ChatCitationResponse,
    extraction_quality_map: dict[str, tuple[str | None, float | None, str]],
) -> ChatCitationResponse:
    """Annotate a citation with document extraction quality and processing status (F315).

    extraction_quality_map maps document_id to (document_profile, extraction_confidence, doc_status).
    Sets doc_extraction_quality, doc_extraction_warning, and doc_processing_warning.
    """
    entry = extraction_quality_map.get(citation.document_id)
    if entry is None:
        return citation
    doc_profile, extraction_conf, doc_status = entry
    is_bad_profile = doc_profile in _EXTRACTION_WARNING_PROFILES
    is_low_conf = (
        extraction_conf is not None and extraction_conf < _EXTRACTION_CONFIDENCE_WARN_THRESHOLD
    )
    extraction_warning = is_bad_profile or is_low_conf
    processing_warning = doc_status in _PROCESSING_INCOMPLETE_STATUSES
    return ChatCitationResponse(
        document_id=citation.document_id,
        chunk_id=citation.chunk_id,
        filename=citation.filename,
        page_number=citation.page_number,
        score=citation.score,
        similarity_score=citation.similarity_score,
        original_rank=citation.original_rank,
        rerank_score=citation.rerank_score,
        rerank_rank=citation.rerank_rank,
        final_rank=citation.final_rank,
        text_snippet=citation.text_snippet,
        start_offset=citation.start_offset,
        end_offset=citation.end_offset,
        source_provider=citation.source_provider,
        source_provider_label=citation.source_provider_label,
        source_title=citation.source_title,
        source_key=citation.source_key,
        source_section=citation.source_section,
        source_deep_link=citation.source_deep_link,
        source_last_synced_at=citation.source_last_synced_at,
        source_trust_status=citation.source_trust_status,
        source_acl_snapshot=citation.source_acl_snapshot,
        conflict_status=citation.conflict_status,
        doc_trust_status=citation.doc_trust_status,
        doc_review_status=citation.doc_review_status,
        doc_review_owner_id=citation.doc_review_owner_id,
        doc_review_due_date=citation.doc_review_due_date,
        doc_expiry_date=citation.doc_expiry_date,
        doc_version_label=citation.doc_version_label,
        doc_review_date=citation.doc_review_date,
        doc_effective_date=citation.doc_effective_date,
        doc_stale_warning=citation.doc_stale_warning,
        doc_expired_warning=citation.doc_expired_warning,
        doc_is_excluded_status=citation.doc_is_excluded_status,
        freshness_state=citation.freshness_state,
        doc_last_updated_at=citation.doc_last_updated_at,
        doc_unreviewed_warning=citation.doc_unreviewed_warning,
        doc_deprecated_warning=citation.doc_deprecated_warning,
        is_table_chunk=citation.is_table_chunk,
        table_caption=citation.table_caption,
        table_row_count=citation.table_row_count,
        table_col_count=citation.table_col_count,
        table_headers=citation.table_headers,
        table_section_context=citation.table_section_context,
        table_extraction_confidence=citation.table_extraction_confidence,
        table_low_confidence_warning=citation.table_low_confidence_warning,
        doc_ocr_quality_status=citation.doc_ocr_quality_status,
        doc_ocr_low_confidence_warning=citation.doc_ocr_low_confidence_warning,
        doc_extraction_quality=doc_profile,
        doc_extraction_warning=extraction_warning,
        doc_processing_warning=processing_warning,
    )


def _build_conflict_context(conflict_result: ConflictDetectionResult) -> str:
    if not conflict_result.applied or conflict_result.agreement_level == "full":
        return ""

    preferred = ", ".join(conflict_result.preferred_document_ids) or "<none>"
    conflicting = ", ".join(conflict_result.conflicting_document_ids) or "<none>"
    pair_lines = [
        f"- {pair.document_id_a} vs {pair.document_id_b}: {pair.topic} ({pair.severity})"
        for pair in conflict_result.conflict_pairs[:5]
    ]
    pair_block = "\n".join(pair_lines) if pair_lines else "- No valid conflict pairs returned."
    return (
        "Source agreement guidance:\n"
        f"- agreement_level: {conflict_result.agreement_level}\n"
        f"- conflict_summary: {conflict_result.conflict_summary or 'Conflicting sources detected.'}\n"
        f"- preferred_document_ids: {preferred}\n"
        f"- conflicting_document_ids: {conflicting}\n"
        f"- conflict_pairs:\n{pair_block}\n"
        "Use the preferred sources as the primary basis, mention disagreements clearly, "
        "and avoid presenting a single certain answer when the sources do not agree.\n"
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
                chunk_type=source_chunk.chunk_type,
                chunk_level=source_chunk.chunk_level,
                parent_text=source_chunk.parent_text,
            )
        )
    return selected_chunks, rerank_result


def _build_prompt(
    *,
    question: str,
    chunks: list[RetrievedChunk],
    parent_context_map: dict[str, str] | None = None,
    conflict_context: str = "",
    answer_language: str | None = None,
    template: str | None = None,
) -> str:
    _ctx = parent_context_map or {}
    return _prompt_service.build_prompt(
        question=question,
        not_found_answer=_NOT_FOUND_ANSWER,
        conflict_context=conflict_context,
        answer_language=answer_language,
        template=template,
        chunks=[
            PromptContextChunk(
                document_id=str(chunk.document_id),
                chunk_id=str(chunk.chunk_id),
                filename=chunk.filename,
                page_number=chunk.page_number,
                text=_ctx.get(str(chunk.chunk_id)) or chunk.text,
                similarity_score=chunk.similarity_score,
                original_rank=chunk.original_rank,
                rerank_score=chunk.rerank_score,
                rerank_rank=chunk.rerank_rank,
                final_rank=chunk.final_rank,
            )
            for chunk in chunks
        ],
    )


def _build_conflict_detection_chunks(
    *,
    chunks: list[RetrievedChunk],
    parent_context_map: dict[str, str] | None,
    trust_map: dict[str, DocumentTrustData],
    org_stale_threshold_days: int | None,
) -> list[ConflictDetectionChunk]:
    context_map = parent_context_map or {}
    detection_chunks: list[ConflictDetectionChunk] = []
    for chunk in chunks:
        trust = trust_map.get(str(chunk.document_id))
        effective_trust_status = (
            _source_freshness_service.compute_effective_trust_status(
                trust,
                org_stale_threshold_days=org_stale_threshold_days,
            )
            if trust is not None
            else "current"
        )
        detection_chunks.append(
            ConflictDetectionChunk(
                chunk_id=str(chunk.chunk_id),
                document_id=str(chunk.document_id),
                text=context_map.get(str(chunk.chunk_id)) or chunk.text,
                similarity_score=chunk.similarity_score,
                trust_status=effective_trust_status,
            )
        )
    return detection_chunks


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


def _compute_freshness_multiplier(stale_count: int, total_count: int) -> float:
    """Map stale-source fraction to a [0.70, 1.0] confidence multiplier."""
    if total_count == 0 or stale_count == 0:
        return 1.0
    stale_fraction = stale_count / total_count
    return max(0.70, 1.0 - stale_fraction * settings.confidence_freshness_stale_penalty)


def _compute_ocr_quality_multiplier(citations: list) -> float:
    """Average OCR-quality multiplier across all citations that carry OCR status."""
    _ocr_map: dict[str, float] = {
        "high": 1.0,
        "not_required": 1.0,
        "medium": settings.confidence_ocr_medium_multiplier,
        "low": settings.confidence_ocr_low_multiplier,
        "failed": settings.confidence_ocr_failed_multiplier,
    }
    multipliers = [
        _ocr_map[q]
        for c in citations
        if (q := getattr(c, "doc_ocr_quality_status", None)) in _ocr_map
    ]
    return round(sum(multipliers) / len(multipliers), 4) if multipliers else 1.0


def _compute_conflict_multiplier(conflict_result: ConflictDetectionResult) -> float:
    """Map conflict agreement_level to a confidence multiplier."""
    level = conflict_result.agreement_level
    if level == "conflicting":
        return max(0.0, 1.0 - settings.confidence_conflict_penalty_conflicting)
    if level == "partial":
        return max(0.0, 1.0 - settings.confidence_conflict_penalty_partial)
    return 1.0


# F315 — evidence quality thresholds
_TABLE_CONFIDENCE_LOW_THRESHOLD = 0.4
_TABLE_CONFIDENCE_VERY_LOW_THRESHOLD = 0.2
_EXTRACTION_CONFIDENCE_WARN_THRESHOLD = 0.5
_EXTRACTION_WARNING_PROFILES = frozenset({"corrupted", "unsupported", "encrypted"})
_PROCESSING_INCOMPLETE_STATUSES = frozenset(
    {"processing", "failed", "extraction_failed", "quarantined", "blocked", "infected"}
)


def _compute_table_quality_multiplier(citations: list) -> float:
    """Average table-extraction quality penalty across table citations (F315).

    Citations that are not table chunks are excluded. A low-confidence table
    (< 0.4) yields a 0.85 multiplier; very low-confidence (< 0.2) yields 0.70.
    """
    multipliers: list[float] = []
    for c in citations:
        if not getattr(c, "is_table_chunk", False):
            continue
        conf = getattr(c, "table_extraction_confidence", None)
        if conf is None:
            continue
        if conf < _TABLE_CONFIDENCE_VERY_LOW_THRESHOLD:
            multipliers.append(0.70)
        elif conf < _TABLE_CONFIDENCE_LOW_THRESHOLD:
            multipliers.append(0.85)
        else:
            multipliers.append(1.0)
    return round(sum(multipliers) / len(multipliers), 4) if multipliers else 1.0


def _compute_extraction_quality_multiplier(citations: list) -> float:
    """Return 0.85 when any citation carries a document extraction warning (F315)."""
    if any(getattr(c, "doc_extraction_warning", False) for c in citations):
        return 0.85
    return 1.0


def _build_evidence_quality_record(citations: list) -> "EvidenceQualityRecord":
    """Build an aggregated evidence quality summary from annotated citations (F315)."""
    table_low_conf_count = sum(
        1 for c in citations if getattr(c, "table_low_confidence_warning", False)
    )
    extraction_warn_count = sum(1 for c in citations if getattr(c, "doc_extraction_warning", False))
    processing_warn_count = sum(1 for c in citations if getattr(c, "doc_processing_warning", False))
    any_incomplete = processing_warn_count > 0

    warning_reasons: list[str] = []
    if table_low_conf_count > 0:
        warning_reasons.append(
            f"{table_low_conf_count} cited table chunk"
            f"{'s have' if table_low_conf_count > 1 else ' has'} low extraction confidence"
            " — table data may be inaccurate."
        )
    if extraction_warn_count > 0:
        warning_reasons.append(
            f"{extraction_warn_count} source document"
            f"{'s have' if extraction_warn_count > 1 else ' has'} poor extraction quality"
            " — text coverage may be incomplete."
        )
    if processing_warn_count > 0:
        warning_reasons.append(
            f"{processing_warn_count} source document"
            f"{'s have' if processing_warn_count > 1 else ' has'} incomplete or failed"
            " processing — content may be missing."
        )

    return EvidenceQualityRecord(
        table_low_confidence_count=table_low_conf_count,
        extraction_warning_count=extraction_warn_count,
        processing_warning_count=processing_warn_count,
        any_incomplete_documents=any_incomplete,
        warning_reasons=warning_reasons,
    )


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


async def _resolve_query_rewrite_preview_enabled(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
) -> bool:
    try:
        return await _feature_flag_service.is_enabled(
            db_session,
            organization_id=organization_id,
            flag_name="query_rewrite_preview",
        )
    except Exception as exc:
        log_query_event(
            event="query.rewrite_preview.feature_flag_fallback",
            organization_id=str(organization_id),
            error=exc.__class__.__name__,
            detail=str(exc),
            enabled=settings.feature_enable_query_rewrite_preview,
        )
        return settings.feature_enable_query_rewrite_preview


_QUERY_INTENT_LABELS: dict[str, str] = {
    "lookup": "Lookup",
    "summary": "Summary",
    "comparison": "Comparison",
    "policy": "Policy",
    "troubleshooting": "Troubleshooting",
    "compliance": "Compliance",
    "connector_search": "Connector search",
    "graph_entity_search": "Graph/entity search",
}


def _infer_query_intent(question: str) -> str:
    normalized = question.lower()
    if any(
        token in normalized
        for token in (
            "connector",
            "connectors",
            "integration",
            "integrations",
            "datasource",
            "data source",
            "slack",
            "jira",
            "salesforce",
            "sharepoint",
            "confluence",
            "google drive",
            "onedrive",
            "box",
        )
    ):
        return "connector_search"
    if any(
        token in normalized
        for token in (
            "graph",
            "entity",
            "entities",
            "relationship",
            "relationships",
            "linked to",
            "connected to",
            "reports to",
            "reporting line",
            "org chart",
        )
    ):
        return "graph_entity_search"
    if any(
        token in normalized
        for token in (
            "compare",
            "comparison",
            "difference",
            "differences",
            "versus",
            "vs ",
            " vs",
            "better than",
            "tradeoff",
            "trade-offs",
            "which is more",
        )
    ):
        return "comparison"
    if any(
        token in normalized
        for token in (
            "troubleshoot",
            "troubleshooting",
            "debug",
            "fix",
            "issue",
            "problem",
            "error",
            "failed",
            "not working",
            "why can't",
            "why is",
        )
    ):
        return "troubleshooting"
    if any(
        token in normalized
        for token in (
            "compliance",
            "compliant",
            "gdpr",
            "hipaa",
            "sox",
            "pci",
            "audit",
            "regulation",
            "regulatory",
            "retention",
            "privacy",
            "legal",
        )
    ):
        return "compliance"
    if any(
        token in normalized
        for token in (
            "summarize",
            "summarise",
            "summary",
            "overview",
            "brief",
            "recap",
            "what does",
            "tell me about",
        )
    ):
        return "summary"
    if any(
        token in normalized
        for token in (
            "policy",
            "policies",
            "guideline",
            "guidelines",
            "procedure",
            "procedures",
            "rule",
            "rules",
            "benefit",
            "benefits",
            "leave",
            "vacation",
            "expense",
            "expenses",
        )
    ):
        return "policy"
    return "lookup"


def _query_complexity(
    *,
    intent: str,
    query_rewrite_result: QueryRewritingResult | None,
    question: str,
) -> str:
    if query_rewrite_result is not None and query_rewrite_result.decomposition_applied:
        return "multi_part"
    if query_rewrite_result is not None and query_rewrite_result.rewriting_applied:
        return "complex"
    if intent in {
        "comparison",
        "policy",
        "troubleshooting",
        "compliance",
        "connector_search",
        "graph_entity_search",
    }:
        return "complex"
    if len(question.split()) >= 18:
        return "complex"
    return "simple"


def _build_query_interpretation_record(
    *,
    question: str,
    query_rewrite_result: QueryRewritingResult | None,
    rewrite_preview_enabled: bool,
) -> QueryInterpretationRecord:
    intent = _infer_query_intent(question)
    strategy = query_rewrite_result.strategy if query_rewrite_result is not None else "original"
    complexity = _query_complexity(
        intent=intent,
        query_rewrite_result=query_rewrite_result,
        question=question,
    )
    preview_available = (
        rewrite_preview_enabled
        and query_rewrite_result is not None
        and (query_rewrite_result.rewriting_applied or query_rewrite_result.decomposition_applied)
    )
    rewritten_query_preview = (
        query_rewrite_result.primary_query
        if preview_available
        and query_rewrite_result is not None
        and query_rewrite_result.primary_query.strip()
        else None
    )
    sub_queries = (
        list(query_rewrite_result.sub_queries)
        if preview_available
        and query_rewrite_result is not None
        and query_rewrite_result.decomposition_applied
        else []
    )
    return QueryInterpretationRecord(
        intent=intent,
        intent_label=_QUERY_INTENT_LABELS.get(intent, "Lookup"),
        complexity=complexity,
        retrieval_strategy=strategy,
        rewrite_preview_enabled=rewrite_preview_enabled,
        rewritten_query_preview=rewritten_query_preview,
        sub_queries=sub_queries,
    )


def _build_search_mode(
    *,
    hybrid_retrieval_enabled: bool,
    graph_context_result: GraphRetrievalResult,
) -> str:
    if graph_context_result.graph_context_used and hybrid_retrieval_enabled:
        return "hybrid+graph"
    if graph_context_result.graph_context_used:
        return "graph"
    if hybrid_retrieval_enabled:
        return "hybrid"
    return "vector"


def _build_retrieval_profile_scope(
    *,
    payload: ChatQueryRequest,
    source_scope_result: ResolvedSourceScope,
    graph_context_result: GraphRetrievalResult,
    document_ids: list[UUID] | None,
) -> str:
    if payload.scope_mode == "none":
        return "none"
    if graph_context_result.graph_context_used:
        return "graph"
    if payload.source_scope is not None:
        if payload.source_scope.mode == "collections":
            return "selected collection"
        if payload.source_scope.mode in {"connector_sources", "connector_items"}:
            return "connector"
        if payload.source_scope.mode == "uploaded":
            return "document"
        if payload.source_scope.mode == "all" and (
            payload.source_scope.collection_ids
            or payload.source_scope.provider_keys
            or payload.source_scope.connection_ids
            or payload.source_scope.provider_source_ids
            or payload.source_scope.external_source_ids
            or payload.source_scope.external_item_ids
        ):
            return "document"
    if document_ids:
        return "document"
    if source_scope_result.label == "All sources":
        return "all documents"
    return "all documents"


def _build_retrieval_filters(
    *,
    payload: ChatQueryRequest,
    source_scope_result: ResolvedSourceScope,
    document_ids: list[UUID] | None,
    graph_context_result: GraphRetrievalResult,
) -> list[str]:
    filters: list[str] = []
    if payload.scope_mode is not None:
        filters.append(f"scope_mode={payload.scope_mode}")
    if document_ids:
        filters.append(f"documents={len(document_ids)}")
    if payload.source_scope is not None:
        scope = payload.source_scope
        if scope.mode != "all":
            filters.append(f"source_scope={scope.mode}")
        if scope.collection_ids:
            filters.append(f"collections={len(scope.collection_ids)}")
        if scope.provider_keys:
            filters.append(f"providers={len(scope.provider_keys)}")
        if scope.connection_ids:
            filters.append(f"connections={len(scope.connection_ids)}")
        if scope.provider_source_ids:
            filters.append(f"provider_sources={len(scope.provider_source_ids)}")
        if scope.external_source_ids:
            filters.append(f"external_sources={len(scope.external_source_ids)}")
        if scope.external_item_ids:
            filters.append(f"external_items={len(scope.external_item_ids)}")
        if scope.document_types:
            filters.append(f"document_types={', '.join(scope.document_types[:3])}")
        if scope.sync_statuses:
            filters.append(f"sync_statuses={', '.join(scope.sync_statuses[:3])}")
    if graph_context_result.graph_context_used:
        filters.append("graph=enabled")
    if source_scope_result.label:
        filters.append(f"scope={source_scope_result.label}")
    # Keep the list short and readable in the trust panel.
    return filters[:8]


def _build_rerank_score_range(chunks: list[RetrievedChunk]) -> tuple[float | None, float | None]:
    scores = [
        score
        for score in (chunk.rerank_score for chunk in chunks)
        if isinstance(score, (int, float))
    ]
    if not scores:
        return None, None
    return min(scores), max(scores)


def _build_retrieval_diagnostics_payload(
    *,
    request_id: str | None,
    rag_profile: object | None,
    rag_profile_source: str,
    payload: ChatQueryRequest,
    source_scope_result: ResolvedSourceScope,
    retrieved_chunks: list[RetrievedChunk],
    selected_chunks: list[RetrievedChunk],
    rerank_applied: bool,
    rerank_diagnostics: object | None,
    hybrid_retrieval_enabled: bool,
    hybrid_vector_hit_count: int,
    hybrid_keyword_hit_count: int,
    query_rewrite_result: object | None,
    graph_context_result: GraphRetrievalResult,
    document_ids: list[UUID] | None,
    final_top_k: int,
) -> dict[str, object]:
    profile_name = getattr(rag_profile, "name", None) if rag_profile is not None else None
    search_mode = _build_search_mode(
        hybrid_retrieval_enabled=hybrid_retrieval_enabled,
        graph_context_result=graph_context_result,
    )
    retrieval_profile_scope = _build_retrieval_profile_scope(
        payload=payload,
        source_scope_result=source_scope_result,
        graph_context_result=graph_context_result,
        document_ids=document_ids,
    )
    retrieval_filters = _build_retrieval_filters(
        payload=payload,
        source_scope_result=source_scope_result,
        document_ids=document_ids,
        graph_context_result=graph_context_result,
    )
    rerank_score_min, rerank_score_max = _build_rerank_score_range(retrieved_chunks)
    rerank_fallback_used = bool(getattr(rerank_diagnostics, "fallback_used", False))
    rerank_fallback_reason = getattr(rerank_diagnostics, "fallback_reason", None)
    return {
        "retrieval_candidate_count": len(retrieved_chunks),
        "retrieval_count": len(retrieved_chunks),
        "selected_count": len(selected_chunks),
        "top_k": final_top_k,
        "search_mode": search_mode,
        "source_scope_mode": payload.source_scope.mode
        if payload.source_scope is not None
        else payload.scope_mode,
        "source_scope_label": source_scope_result.label,
        "retrieval_profile_name": profile_name,
        "retrieval_profile_scope": retrieval_profile_scope,
        "retrieval_profile_source": rag_profile_source,
        "retrieval_filters": retrieval_filters,
        "rerank_applied": rerank_applied,
        "rerank_provider": getattr(rerank_diagnostics, "provider_key", None)
        if rerank_diagnostics is not None
        else None,
        "rerank_model": getattr(rerank_diagnostics, "model_name", None)
        if rerank_diagnostics is not None
        else None,
        "rerank_score_min": rerank_score_min,
        "rerank_score_max": rerank_score_max,
        "rerank_fallback_used": rerank_fallback_used,
        "rerank_fallback_reason": rerank_fallback_reason,
        "request_id": request_id,
        "trace_request_id": request_id,
    }


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


def _build_trust_metadata(
    *,
    organization_id: UUID,
    message_id: str,
    question: str,
    query_rewrite_preview_enabled: bool,
    not_found: bool,
    citation_validation_failed: bool,
    verification_failed: bool,
    confidence_score: float,
    confidence_category: str,
    confidence_explanation: object,
    citations: list[ChatCitationResponse],
    retrieval_diagnostics_payload: dict[str, object],
    retrieved_chunks: list,
    selected_chunks: list,
    rerank_applied: bool,
    rerank_diagnostics: object | None,
    hybrid_vector_hit_count: int,
    hybrid_keyword_hit_count: int,
    query_rewrite_result: object | None,
    parent_context_expanded_count: int,
    graph_context_result: GraphRetrievalResult,
    freshness_excluded_count: int,
    freshness_boosted_count: int,
    freshness_stale_count: int,
    freshness_unreviewed_count: int,
    freshness_deprecated_count: int,
    freshness_draft_count: int,
    freshness_all_excluded_fallback: bool,
    grounded_verifier_result: GroundedVerifierResult | None,
    llm_model: str | None,
    llm_provider: str | None,
    embedding_model: str | None,
    llm_fallback_used: bool,
    llm_fallback_from: str | None,
    llm_fallback_to: str | None,
    llm_fallback_reason: str | None,
    answer_prompt_version: object | None,
    conflict_detection_result: ConflictDetectionResult,
    ai_policy_applied: bool,
    ai_policy_result: object,
    generated_at: datetime,
) -> AnswerTrustMetadataResponse:
    """Build the versioned trust metadata contract from pipeline state.

    Never includes raw prompts, chain-of-thought, ACL snapshots, or internal
    version UUIDs — only user-facing fields that the trust panel needs.
    """
    expl = confidence_explanation

    source_freshness_warning = freshness_all_excluded_fallback or any(
        getattr(c, "doc_stale_warning", False)
        or getattr(c, "doc_expired_warning", False)
        or getattr(c, "doc_is_excluded_status", False)
        or getattr(c, "doc_unreviewed_warning", False)
        or getattr(c, "doc_deprecated_warning", False)
        or getattr(c, "doc_draft_warning", False)
        for c in citations
    )

    citation_records = [
        CitationTrustRecord(
            document_id=c.document_id,
            chunk_id=c.chunk_id,
            filename=c.filename,
            page_number=c.page_number,
            score=c.score,
            similarity_score=c.similarity_score,
            rerank_score=c.rerank_score,
            original_rank=c.original_rank,
            final_rank=c.final_rank,
            text_snippet=c.text_snippet,
            source_provider=c.source_provider,
            source_provider_label=c.source_provider_label,
            source_title=c.source_title,
            source_key=c.source_key,
            source_section=c.source_section,
            source_deep_link=c.source_deep_link,
            source_last_synced_at=c.source_last_synced_at,
            source_trust_status=c.source_trust_status,
            conflict_status=c.conflict_status,
            doc_trust_status=c.doc_trust_status,
            doc_quality_state=getattr(c, "doc_quality_state", None),
            doc_review_status=c.doc_review_status,
            doc_version_label=c.doc_version_label,
            doc_review_due_date=c.doc_review_due_date,
            doc_expiry_date=c.doc_expiry_date,
            doc_stale_warning=c.doc_stale_warning,
            doc_expired_warning=c.doc_expired_warning,
            doc_is_excluded_status=c.doc_is_excluded_status,
            is_table_chunk=c.is_table_chunk,
            table_caption=c.table_caption,
            table_row_count=c.table_row_count,
            table_col_count=c.table_col_count,
            table_headers=list(c.table_headers),
            doc_ocr_quality_status=c.doc_ocr_quality_status,
            doc_ocr_low_confidence_warning=c.doc_ocr_low_confidence_warning,
            freshness_state=getattr(c, "freshness_state", None),
            doc_last_updated_at=getattr(c, "doc_last_updated_at", None),
            doc_review_owner_id=getattr(c, "doc_review_owner_id", None),
            doc_unreviewed_warning=getattr(c, "doc_unreviewed_warning", False),
            doc_deprecated_warning=getattr(c, "doc_deprecated_warning", False),
            doc_draft_warning=getattr(c, "doc_draft_warning", False),
            table_extraction_confidence=getattr(c, "table_extraction_confidence", None),
            table_low_confidence_warning=getattr(c, "table_low_confidence_warning", False),
            doc_extraction_quality=getattr(c, "doc_extraction_quality", None),
            doc_extraction_warning=getattr(c, "doc_extraction_warning", False),
            doc_processing_warning=getattr(c, "doc_processing_warning", False),
        )
        for c in ([] if not_found else citations)
    ]

    prompt_key: str | None = None
    prompt_ver: int | None = None
    if answer_prompt_version is not None:
        prompt_key = PromptTemplateKey.answer_generation.value
        prompt_ver = getattr(answer_prompt_version, "version_number", None)

    gv_applied = grounded_verifier_result is not None and grounded_verifier_result.applied
    query_interpretation = _build_query_interpretation_record(
        question=question,
        query_rewrite_result=query_rewrite_result,
        rewrite_preview_enabled=query_rewrite_preview_enabled,
    )

    return AnswerTrustMetadataResponse(
        schema_version="1",
        organization_id=str(organization_id),
        message_id=message_id,
        not_found=not_found,
        citation_validation_failed=citation_validation_failed,
        verification_failed=verification_failed,
        confidence=ConfidenceTrustRecord(
            score=confidence_score,
            category=confidence_category,
            trust_level=expl.trust_level,
            citation_support_score=expl.citation_support_score,
            citation_validation_score=expl.citation_validation_score,
            citation_coverage_score=expl.citation_coverage_score,
            retrieval_agreement_score=expl.retrieval_agreement_score,
            top_similarity=expl.top_similarity,
            average_similarity=expl.average_similarity,
            top_rerank_score=expl.top_rerank_score,
            raw_score=expl.raw_score,
            citation_validation_multiplier=expl.citation_validation_multiplier,
            not_found_penalty_multiplier=expl.not_found_penalty_multiplier,
            freshness_multiplier=expl.freshness_multiplier,
            ocr_quality_multiplier=expl.ocr_quality_multiplier,
            conflict_multiplier=expl.conflict_multiplier,
            table_quality_multiplier=expl.table_quality_multiplier,
            extraction_quality_multiplier=expl.extraction_quality_multiplier,
            graph_evidence_boost=expl.graph_evidence_boost,
            verification_support_score=expl.verification_support_score,
            not_found_signal=expl.not_found_signal,
            no_context=expl.no_context,
            reasons=[
                ConfidenceReasonRecord(
                    code=r.code,
                    label=r.label,
                    impact=r.impact,
                    magnitude=r.magnitude,
                )
                for r in expl.reasons
            ],
        ),
        citations=citation_records,
        retrieval=RetrievalDiagnosticsRecord(
            **retrieval_diagnostics_payload,
            hybrid_retrieval_enabled=settings.feature_enable_hybrid_retrieval,
            hybrid_vector_hit_count=hybrid_vector_hit_count,
            hybrid_keyword_hit_count=hybrid_keyword_hit_count,
            query_rewriting_applied=query_rewrite_result is not None
            and query_rewrite_result.rewriting_applied,
            query_decomposed=query_rewrite_result is not None
            and query_rewrite_result.decomposition_applied,
            sub_query_count=(
                len(query_rewrite_result.sub_queries) if query_rewrite_result is not None else 0
            ),
            parent_context_expanded_count=parent_context_expanded_count,
            graph_context_used=graph_context_result.graph_context_used,
            graph_context_unavailable=graph_context_result.graph_context_unavailable,
            graph_chunk_count=graph_context_result.graph_chunk_count,
            freshness_excluded_count=freshness_excluded_count,
            freshness_boosted_count=freshness_boosted_count,
        ),
        query_interpretation=query_interpretation,
        grounded_verification=GroundedVerificationRecord(
            applied=gv_applied,
            verdict=grounded_verifier_result.verdict if gv_applied else None,
            score=grounded_verifier_result.verification_score if gv_applied else None,
            aggregate_support_score=grounded_verifier_result.aggregate_support_score
            if grounded_verifier_result is not None
            else 0.0,
            claim_count=grounded_verifier_result.claim_count
            if grounded_verifier_result is not None
            else 0,
            supported_count=grounded_verifier_result.supported_claim_count
            if grounded_verifier_result is not None
            else 0,
            partially_supported_count=grounded_verifier_result.partially_supported_claim_count
            if grounded_verifier_result is not None
            else 0,
            unsupported_count=grounded_verifier_result.unsupported_claim_count
            if grounded_verifier_result is not None
            else 0,
            unverifiable_count=grounded_verifier_result.unverifiable_claim_count
            if grounded_verifier_result is not None
            else 0,
            removed_count=len(grounded_verifier_result.removed_claims)
            if grounded_verifier_result is not None
            else 0,
            reason_codes=list(grounded_verifier_result.reason_codes)
            if grounded_verifier_result is not None
            else [],
            claims=_build_claim_support_records(
                grounded_verifier_result=grounded_verifier_result if gv_applied else None
            ),
            mode=grounded_verifier_result.mode if grounded_verifier_result is not None else None,
            threshold=grounded_verifier_result.threshold
            if grounded_verifier_result is not None
            else None,
        ),
        model=ModelMetadataRecord(
            llm_model=llm_model,
            llm_provider=llm_provider,
            embedding_model=embedding_model,
            fallback_used=llm_fallback_used,
            fallback_from=llm_fallback_from,
            fallback_to=llm_fallback_to,
            fallback_reason=llm_fallback_reason,
            prompt_template_key=prompt_key,
            prompt_template_version=prompt_ver,
        ),
        conflict=ConflictStatusRecord(
            detected=conflict_detection_result.conflict_detected,
            agreement_level=conflict_detection_result.agreement_level,
            conflict_count=len(conflict_detection_result.conflict_pairs),
            conflicting_document_ids=_list_or_empty(
                conflict_detection_result.conflicting_document_ids
            ),
            preferred_document_ids=_list_or_empty(conflict_detection_result.preferred_document_ids),
            conflict_summary=conflict_detection_result.conflict_summary
            if conflict_detection_result.conflict_detected
            else None,
        ),
        policy=PolicyEnforcementRecord(
            applied=ai_policy_applied,
            outcome=getattr(ai_policy_result, "outcome", None) if ai_policy_applied else None,
            violated_rules=list(getattr(ai_policy_result, "violated_rules", []) or []),
            warning_flags=list(getattr(ai_policy_result, "warning_flags", []) or []),
            has_disclaimer=bool(getattr(ai_policy_result, "disclaimer_text", None))
            if ai_policy_applied
            else False,
        ),
        freshness=SourceFreshnessRecord(
            warning=source_freshness_warning,
            warning_reason="One or more citations come from stale, draft, unreviewed, deprecated, or archived sources."
            if source_freshness_warning
            else None,
            warning_reasons=_source_freshness_service.build_warning_reasons(
                stale_count=freshness_stale_count,
                excluded_count=freshness_excluded_count,
                unreviewed_count=freshness_unreviewed_count,
                deprecated_count=freshness_deprecated_count,
                draft_count=freshness_draft_count,
                all_excluded_fallback=freshness_all_excluded_fallback,
            ),
            stale_count=freshness_stale_count,
            excluded_count=freshness_excluded_count,
            boosted_count=freshness_boosted_count,
            unreviewed_count=freshness_unreviewed_count,
            deprecated_count=freshness_deprecated_count,
            draft_count=freshness_draft_count,
            all_excluded_fallback=freshness_all_excluded_fallback,
        ),
        evidence_quality=_build_evidence_quality_record(citation_records),
        generated_at=generated_at,
    )


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
    await plan_enforcement_service.ensure_within_limit(
        db_session,
        organization_id=organization_id,
        quota_type=QuotaType.questions,
        requested_amount=1,
        resource="chat questions",
        guidance="Upgrade your plan or reduce chat volume.",
    )
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
    # Policy-engine authorization filter on the resolved document scope.
    # Admins bypass via rule 5; non-admins have each document checked.
    if document_ids and not frozenset({"owner", "admin"}).intersection(user_roles):
        from app.domains.documents.repositories.documents import DocumentRepository as _DocRepo

        _doc_repo_chat = _DocRepo()
        docs_for_auth = []
        for doc_id in document_ids:
            doc = await _doc_repo_chat.get_document(
                db_session, document_id=doc_id, organization_id=organization_id
            )
            if doc is not None:
                docs_for_auth.append(doc)

        if docs_for_auth:
            accessible_col_ids = await get_subject_accessible_collection_ids(
                db_session,
                organization_id=organization_id,
                user_id=user_id,
                user_roles=user_roles,
            )
            resource_contexts = await build_document_resource_contexts_batch(
                db_session,
                documents=docs_for_auth,
                organization_id=organization_id,
                subject_accessible_collection_ids=accessible_col_ids,
            )
            allowed_ids = {
                ctx.resource_id
                for ctx in await _authorization_service.filter_accessible_resources(
                    principal, Action.chat, resource_contexts, db_session
                )
            }
            document_ids = [d for d in document_ids if str(d) in allowed_ids]

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

    # Query rewriting and decomposition (F295).
    # Runs after language detection so the detected language is available for context.
    # Scope filters (document_ids, org tenancy) are applied in the retrieval layer and
    # are never altered here — rewriting cannot widen access.
    if settings.feature_enable_query_rewriting and not injection_check.blocked:
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

        embed_started = perf_counter()
        try:
            embed_tasks = [
                _query_retrieval_service.embed_query(question=q) for q in _retrieval_queries
            ]
            embed_results = await asyncio.gather(*embed_tasks)
            # Sum token counts across all embedding calls.
            embedding_prompt_tokens = sum(tokens for _, tokens in embed_results)
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
            # Collect chunks from all retrieval queries, deduplicating by chunk_id.
            # When the same chunk appears in multiple sub-query results we keep the
            # instance with the highest similarity score.
            _merged_chunks: dict[str, RetrievedChunk] = {}
            _primary_query_for_kw = _retrieval_queries[0]

            for (query_vector, _), retrieval_q in zip(
                embed_results, _retrieval_queries, strict=False
            ):
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
                        query=retrieval_q,
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
                    batch_chunks = [_hybrid_to_retrieved_chunk(c) for c in hybrid_result.candidates]
                    # Accumulate hybrid stats only for the primary query.
                    if retrieval_q == _primary_query_for_kw:
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
            # Non-admins are filtered; admins bypass via policy-engine rule 5.
            if retrieved_chunks and not frozenset({"owner", "admin"}).intersection(user_roles):
                from app.domains.documents.repositories.documents import (
                    DocumentRepository as _DocRepoForCite,
                )

                _cite_doc_repo = _DocRepoForCite()
                _chunk_docs = []
                _seen_doc_ids: set[str] = set()
                for _chunk in retrieved_chunks:
                    _did = str(_chunk.document_id)
                    if _did not in _seen_doc_ids:
                        _seen_doc_ids.add(_did)
                        _d = await _cite_doc_repo.get_document(
                            db_session,
                            document_id=_chunk.document_id,
                            organization_id=organization_id,
                        )
                        if _d is not None:
                            _chunk_docs.append(_d)

                if _chunk_docs:
                    _cite_col_ids = await get_subject_accessible_collection_ids(
                        db_session,
                        organization_id=organization_id,
                        user_id=user_id,
                        user_roles=user_roles,
                    )
                    _cite_contexts = await build_document_resource_contexts_batch(
                        db_session,
                        documents=_chunk_docs,
                        organization_id=organization_id,
                        subject_accessible_collection_ids=_cite_col_ids,
                    )
                    _allowed_cite_ids = {
                        ctx.resource_id
                        for ctx in await _authorization_service.filter_accessible_resources(
                            principal, Action.cite, _cite_contexts, db_session
                        )
                    }
                    retrieved_chunks = [
                        c for c in retrieved_chunks if str(c.document_id) in _allowed_cite_ids
                    ]

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
        not_found = (
            len(selected_chunks) == 0 or confidence_score < settings.confidence_not_found_threshold
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
                        elif grounded_verifier_result.unsupported_claim_count > 0:
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
        )
        assistant_message.trust_metadata_json = trust_metadata.model_dump(mode="json")
        db_session.add(assistant_message)
        await db_session.flush()

        for citation in citations:
            document_uuid = _parse_uuid_or_none(citation.document_id)
            chunk_uuid = _parse_uuid_or_none(citation.chunk_id)
            if document_uuid is None or chunk_uuid is None:
                continue
            await chat_repository.create_citation(
                db_session,
                chat_message_id=assistant_message.id,
                document_id=document_uuid,
                chunk_id=chunk_uuid,
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

        await plan_enforcement_service.record_usage(
            db_session,
            organization_id=organization_id,
            quota_type=QuotaType.questions,
            amount=1,
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
        citations=[] if not_found else citations,
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
        category=fb.category,  # type: ignore[arg-type]
        question_text=fb.question_text,
        answer_text=fb.answer_text,
        model_name=fb.model_name,
        rag_profile_id=str(fb.rag_profile_id) if fb.rag_profile_id else None,
        retain_until=fb.retain_until,
        redacted_at=fb.redacted_at,
        converted_to_eval_question_id=str(fb.converted_to_eval_question_id)
        if fb.converted_to_eval_question_id
        else None,
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
        trust_metadata_json=diag.trust_metadata if diag else None,
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
                    rerank_settings.max_input_candidates or settings.rerank_default_input_candidates
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
                for citation in citations:
                    document_uuid = _parse_uuid_or_none(citation.document_id)
                    chunk_uuid = _parse_uuid_or_none(citation.chunk_id)
                    if document_uuid is None or chunk_uuid is None:
                        continue
                    await chat_repository.create_citation(
                        db_session,
                        chat_message_id=assistant_message.id,
                        document_id=document_uuid,
                        chunk_id=chunk_uuid,
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
                    freshness_all_excluded_fallback=freshness_all_excluded_fallback,
                    grounded_verifier_result=grounded_verifier_result,
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
