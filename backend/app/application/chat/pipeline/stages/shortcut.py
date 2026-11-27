"""Stage 4: verified-answer shortcut evaluation (R05-05), off by default.

With ``CHAT_VERIFIED_ANSWER_SHORTCUT_ENABLED=true`` a grounded question is compared with the
organisation's published verified answers (exact normalised question equality only, see
``shortcut_matcher``). A matching card counts as a hit only when every citation passes the
same checks a generated answer's sources pass:

- the document exists in the organisation and its connector item is usable
  (``ensure_document_ids_access``), and it is indexed;
- the principal may read it (``_filter_authorized_document_ids_for_chat``) and cite it
  (``filter_chunks_by_cite_access``);
- it is inside the run's resolved document scope (stage 1);
- the citation's ``chunk_id`` exists in that document.

Any failure, or a card that requires citations with none valid, is no hit.

Returning the card as the answer is **not enabled yet**: the response contract requires a
numeric ``confidence_score`` (``ChatQueryResponse`` and ``ConfidenceTrustRecord``), and the
plan forbids inventing one for a human-verified answer. Until that contract decision is made
the stage only evaluates (shadow mode): it records ``ctx.verified_answer_match``, the metric
``rudix_chat_verified_answer_shortcut_total{result}``, and a log line with the result and
card id, and the run continues to retrieval and generation unchanged.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.chat.citation_access import filter_chunks_by_cite_access
from app.application.chat.pipeline.context import ChatContext
from app.application.chat.scope_inventory import _filter_authorized_document_ids_for_chat
from app.auth.dependencies import ensure_document_ids_access
from app.core.config import settings
from app.core.logging import log_query_event
from app.core.metrics import record_chat_verified_answer_shortcut
from app.domains.chat.schemas.chat import ChatQueryRequest
from app.domains.verified_answers.services.shortcut_matcher import (
    CandidateCitation,
    VerifiedAnswerCandidate,
    VerifiedAnswerMatch,
    find_exact_match,
    load_candidates,
)
from app.models.document import Document, DocumentChunk
from app.models.enums import DocumentStatus


def single_collection_scope(payload: ChatQueryRequest) -> UUID | None:
    """The request's collection when it is scoped to exactly one collection."""
    scope = payload.source_scope
    if scope is None or scope.mode != "collections" or len(scope.collection_ids) != 1:
        return None
    try:
        return UUID(scope.collection_ids[0])
    except ValueError:
        return None


class ShortcutStage:
    name = "shortcut"
    runs_when_terminal = True
    optional = True

    async def run(self, ctx: ChatContext) -> None:
        if not settings.chat_verified_answer_shortcut_enabled or not _grounded(ctx):
            return None
        async with ctx.sessions.read() as db_session:
            match = await evaluate_shortcut(ctx, db_session)
        ctx.verified_answer_match = match
        record_chat_verified_answer_shortcut(match.result)
        log_query_event(
            event="query.verified_answer_shortcut.evaluated",
            organization_id=str(ctx.request.organization_id),
            user_id=str(ctx.request.user_id),
            result=match.result,
            verified_answer_id=str(match.verified_answer_id) if match.verified_answer_id else None,
            valid_citation_count=len(match.valid_citations),
        )
        return None


def _grounded(ctx: ChatContext) -> bool:
    cfg = ctx.config
    return (
        not ctx.terminal
        and not cfg.blocked
        and cfg.answer_mode_result is not None
        and cfg.answer_mode_result.mode == "grounded"
        and not cfg.scope_inventory_requested
    )


async def evaluate_shortcut(ctx: ChatContext, db_session: AsyncSession) -> VerifiedAnswerMatch:
    req = ctx.request
    candidate_set = await load_candidates(db_session, organization_id=req.organization_id)
    if candidate_set.over_cap:
        return VerifiedAnswerMatch(result="over_cap")
    candidate = find_exact_match(
        candidate_set.candidates,
        question=req.payload.question,
        collection_id=single_collection_scope(req.payload),
        today=datetime.now(UTC).date(),
    )
    if candidate is None:
        return VerifiedAnswerMatch(result="no_match")
    valid = await validate_citations(ctx, db_session, candidate)
    if valid is None:
        return VerifiedAnswerMatch(result="citation_rejected", verified_answer_id=candidate.id)
    return VerifiedAnswerMatch(result="hit", verified_answer_id=candidate.id, valid_citations=valid)


async def validate_citations(
    ctx: ChatContext,
    db_session: AsyncSession,
    candidate: VerifiedAnswerCandidate,
) -> list[CandidateCitation] | None:
    """Every citation of ``candidate`` if all pass the checks, else ``None`` (fail closed)."""
    req = ctx.request
    citations = candidate.citations
    scope_ids = ctx.scope.document_ids
    if scope_ids is not None and not scope_ids:
        return None
    if not citations:
        return [] if not candidate.requires_citations else None
    if any(citation.chunk_id is None for citation in citations):
        return None
    document_ids = list(dict.fromkeys(citation.document_id for citation in citations))
    if scope_ids is not None and not set(document_ids) <= set(scope_ids):
        return None
    try:
        await ensure_document_ids_access(
            document_ids=[str(document_id) for document_id in document_ids],
            principal=req.principal,
            db_session=db_session,
        )
    except HTTPException:
        return None
    readable = await _filter_authorized_document_ids_for_chat(
        db_session,
        principal=req.principal,
        organization_id=req.organization_id,
        user_id=req.user_id,
        user_roles=req.user_roles,
        document_ids=document_ids,
    )
    if readable is None or set(readable) != set(document_ids):
        return None
    citable = await filter_chunks_by_cite_access(
        db_session,
        principal=req.principal,
        organization_id=req.organization_id,
        user_id=req.user_id,
        user_roles=req.user_roles,
        chunks=citations,
    )
    if len(citable) != len(citations):
        return None
    if not await _chunks_exist(db_session, req.organization_id, citations):
        return None
    return list(citations)


async def _chunks_exist(
    db_session: AsyncSession, organization_id: UUID, citations: list[CandidateCitation]
) -> bool:
    """Each citation's chunk exists in its document, and the document is indexed."""
    chunk_ids = {citation.chunk_id for citation in citations if citation.chunk_id is not None}
    result = await db_session.execute(
        select(DocumentChunk.id, DocumentChunk.document_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.id.in_(chunk_ids),
            Document.organization_id == organization_id,
            Document.status == DocumentStatus.indexed.value,
        )
    )
    found = {(chunk_id, document_id) for chunk_id, document_id in result.all()}
    return all((citation.chunk_id, citation.document_id) in found for citation in citations)
