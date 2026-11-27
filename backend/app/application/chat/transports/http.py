"""HTTP adapter of the chat pipeline: ``POST /api/v1/chat`` behind ``CHAT_PIPELINE_V2`` (R05-01).

Runs the pipeline on the request session, collects (and ignores) its events, and builds the
same ``ChatQueryResponse`` the legacy ``query_chat`` body returns. Pipeline refusals become the
same safe ``HTTPException`` payloads; the quota ``HTTPException`` passes through unchanged.

R05-02: the request session serves every phase; each phase ends with a commit, so the
connection goes back to the pool before rewriting, retrieval calls, and generation.
"""

from dataclasses import replace
from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.pipeline.context import ChatContext
from app.application.chat.pipeline.deps import ChatPipelineDeps, EnsureQuota, default_deps
from app.application.chat.pipeline.errors import ChatPipelineError
from app.application.chat.pipeline.events import CollectingEmitter
from app.application.chat.pipeline.pipeline import ChatPipeline
from app.application.chat.pipeline.request_helpers import _principal_user_and_org
from app.application.chat.pipeline.sessions import ShortSessionScope
from app.application.chat.transports.http_debug import build_debug_response
from app.auth.models import AuthenticatedPrincipal
from app.domains.chat.schemas.chat import (
    ChatConfidenceExplanationResponse,
    ChatConflictPairResponse,
    ChatQueryRequest,
    ChatQueryResponse,
)
from app.domains.chat.services.chat_values import _list_or_empty


async def run_http_query(
    *,
    payload: ChatQueryRequest,
    principal: AuthenticatedPrincipal,
    db_session: AsyncSession,
    request_id: str | None,
    ensure_quota: EnsureQuota,
    deps: ChatPipelineDeps = default_deps,
) -> ChatQueryResponse:
    """Answer one question over HTTP. ``ensure_quota`` is read from the chat module at call
    time so a rebinding of ``chat.ensure_chat_quota`` reaches the pipeline."""
    pipeline = ChatPipeline(replace(deps, ensure_quota=ensure_quota))
    _, organization_id = _principal_user_and_org(principal)
    try:
        ctx = await pipeline.run(
            payload,
            principal,
            "http",
            CollectingEmitter(),
            ShortSessionScope(organization_id=organization_id, request_session=db_session),
            request_id,
        )
    except ChatPipelineError as exc:
        raise exc.to_http_exception() from exc
    return build_chat_query_response(ctx)


def build_chat_query_response(ctx: ChatContext) -> ChatQueryResponse:
    gen = ctx.generation
    ver = ctx.verification
    out = ctx.persist
    conflict = ctx.retrieval.conflict_detection_result
    effective_policy = ctx.config.ai_effective_policy
    explanation = ver.confidence_explanation
    assert ctx.ids.chat_session_id is not None and out.assistant_message is not None
    assert effective_policy is not None and explanation is not None
    citations = gen.citations
    freshness_warning = any(
        citation.doc_stale_warning
        or citation.doc_expired_warning
        or citation.doc_is_excluded_status
        for citation in citations
    )
    policy_applied = effective_policy.source != "none"
    return ChatQueryResponse(
        chat_session_id=str(ctx.ids.chat_session_id),
        message_id=str(out.assistant_message.id),
        answer=gen.answer,
        confidence_score=ver.confidence_score,
        confidence_category=cast(Literal["low", "medium", "high"], ver.confidence_category),
        confidence_explanation=ChatConfidenceExplanationResponse(
            top_similarity=explanation.top_similarity,
            average_similarity=explanation.average_similarity,
            top_rerank_score=explanation.top_rerank_score,
            citation_support_score=explanation.citation_support_score,
            citation_validation_score=explanation.citation_validation_score,
            citation_coverage_score=explanation.citation_coverage_score,
            retrieval_agreement_score=explanation.retrieval_agreement_score,
            raw_score=explanation.raw_score,
            citation_validation_multiplier=explanation.citation_validation_multiplier,
            not_found_penalty_multiplier=explanation.not_found_penalty_multiplier,
            no_context=explanation.no_context,
            not_found_signal=explanation.not_found_signal,
            weights=explanation.weights,
            thresholds=explanation.thresholds,
        ),
        not_found=gen.not_found,
        citations=[] if gen.not_found else out.response_citations,
        citation_validation_failed=ver.citation_validation_failed,
        verification_failed=ver.verification_failed,
        agreement_level=conflict.agreement_level,
        conflict_detected=conflict.conflict_detected,
        conflict_summary=conflict.conflict_summary if conflict.conflict_detected else None,
        conflicting_document_ids=cast(list[str], _list_or_empty(conflict.conflicting_document_ids)),
        preferred_document_ids=cast(list[str], _list_or_empty(conflict.preferred_document_ids)),
        conflict_pairs=[
            ChatConflictPairResponse(
                document_id_a=pair.document_id_a,
                document_id_b=pair.document_id_b,
                topic=pair.topic,
                severity=pair.severity,
            )
            for pair in conflict.conflict_pairs
        ],
        source_freshness_warning=freshness_warning,
        source_freshness_warning_reason=(
            "One or more citations come from stale, expired, or archived sources."
            if freshness_warning
            else None
        ),
        policy_applied=policy_applied,
        policy_outcome=ver.ai_policy_result.outcome if policy_applied else None,
        policy_violated_rules=ver.ai_policy_result.violated_rules,
        policy_warning_flags=ver.ai_policy_result.warning_flags,
        policy_disclaimer=ver.ai_policy_result.disclaimer_text
        if not ver.ai_policy_result.blocked
        else None,
        trust_metadata=out.trust_metadata,
        debug=build_debug_response(ctx),
        created_at=out.assistant_message.created_at,
    )
