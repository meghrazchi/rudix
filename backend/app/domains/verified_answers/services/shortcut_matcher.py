"""Verified-answer candidates and the exact-match rule of the chat shortcut (R05-05).

The organisation's published cards are cached as plain DTOs under the organisation scope
(namespace ``verified_answer_candidates``, TTL ``CACHE_TTL_POLICIES_SECONDS``). Any write to
a card or its citations bumps the organisation's cache version on commit
(``app.core.cache_invalidation``). An organisation with more published cards than
``CHAT_VERIFIED_ANSWER_MAX_CANDIDATES`` is not cached and never shortcuts.

Matching is exact equality of the normalised question (NFKC, casefold, collapsed
whitespace), never ``ILIKE`` or similarity. A card matches only when it is unexpired and its
collection is ``NULL`` or equals the request's single collection scope. Permission checks
on the card's citations happen in the chat pipeline (stage 4), not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Final
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import OrgScope, get_or_load
from app.core.config import settings
from app.core.question_normalization import normalise_question
from app.domains.verified_answers.repositories.verified_answers import VerifiedAnswerRepository
from app.models.verified_answer import VerifiedAnswer

NAMESPACE_VERIFIED_ANSWER_CANDIDATES: Final = "verified_answer_candidates"


class CandidateCitation(BaseModel):
    document_id: UUID
    chunk_id: UUID | None = None
    text_snippet: str | None = None
    page_number: int | None = None
    citation_order: int = 0


class VerifiedAnswerCandidate(BaseModel):
    id: UUID
    normalised_question: str
    answer_text: str
    collection_id: UUID | None = None
    requires_citations: bool = True
    expiry_date: date | None = None
    citations: list[CandidateCitation] = Field(default_factory=list)

    @classmethod
    def from_model(cls, answer: VerifiedAnswer) -> VerifiedAnswerCandidate:
        return cls(
            id=answer.id,
            normalised_question=normalise_question(answer.question),
            answer_text=answer.answer_text,
            collection_id=answer.collection_id,
            requires_citations=answer.requires_citations,
            expiry_date=answer.expiry_date,
            citations=[
                CandidateCitation(
                    document_id=citation.document_id,
                    chunk_id=citation.chunk_id,
                    text_snippet=citation.text_snippet,
                    page_number=citation.page_number,
                    citation_order=citation.citation_order,
                )
                for citation in sorted(answer.citations, key=lambda c: c.citation_order)
            ],
        )


class VerifiedAnswerCandidateSet(BaseModel):
    over_cap: bool = False
    candidates: list[VerifiedAnswerCandidate] = Field(default_factory=list)


_CANDIDATE_SET_ADAPTER: Final = TypeAdapter(VerifiedAnswerCandidateSet)
_repository = VerifiedAnswerRepository()


async def load_candidates(
    db_session: AsyncSession,
    *,
    organization_id: UUID,
    repository: VerifiedAnswerRepository | None = None,
) -> VerifiedAnswerCandidateSet:
    """The organisation's published cards, cached per organisation."""
    cap = settings.chat_verified_answer_max_candidates
    repo = repository or _repository

    async def load() -> VerifiedAnswerCandidateSet:
        rows = await repo.list_published_for_shortcut(
            db_session, organization_id=organization_id, limit=cap + 1
        )
        if len(rows) > cap:
            return VerifiedAnswerCandidateSet(over_cap=True)
        return VerifiedAnswerCandidateSet(
            candidates=[VerifiedAnswerCandidate.from_model(row) for row in rows]
        )

    return await get_or_load(
        scope=OrgScope(organization_id),
        namespace=NAMESPACE_VERIFIED_ANSWER_CANDIDATES,
        key_id=f"published:cap{cap}",
        ttl=settings.cache_ttl_policies_seconds,
        adapter=_CANDIDATE_SET_ADAPTER,
        loader=load,
    )


def find_exact_match(
    candidates: list[VerifiedAnswerCandidate],
    *,
    question: str,
    collection_id: UUID | None,
    today: date,
) -> VerifiedAnswerCandidate | None:
    """The card whose normalised question equals ``question``'s, or ``None``.

    A card scoped to the request's collection wins over an unscoped one; otherwise the
    newest published card wins (the candidate list is ordered newest first).
    """
    needle = normalise_question(question)
    if not needle:
        return None
    matches = [
        candidate
        for candidate in candidates
        if candidate.normalised_question == needle
        and (candidate.expiry_date is None or candidate.expiry_date >= today)
        and (candidate.collection_id is None or candidate.collection_id == collection_id)
    ]
    if not matches:
        return None
    scoped = [c for c in matches if c.collection_id is not None]
    return scoped[0] if scoped else matches[0]


@dataclass
class VerifiedAnswerMatch:
    """Outcome of stage 4 for one run (names and ids only, never answer text)."""

    result: str
    verified_answer_id: UUID | None = None
    valid_citations: list[CandidateCitation] = field(default_factory=list)
