"""Batched citation reads and writes for chat messages (R04-03).

Message history endpoints used to run one citation query (and one provenance query) per
assistant message, and answer persistence ran ``INSERT`` + ``SELECT`` per citation. These
helpers keep the statement count constant: one citation query for a whole page of messages,
one provenance query for all cited documents, and one ``INSERT`` for all citations of an
answer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.chat.repositories.chat import ChatRepository, CitationInsert
from app.domains.chat.schemas.chat import ChatCitationResponse
from app.domains.connectors.services.source_provenance import SourceProvenanceService
from app.models.chat import ChatMessage
from app.models.citation import Citation
from app.models.enums import ChatRole

ProvenanceDecorator = Callable[[ChatCitationResponse, Any | None], ChatCitationResponse]

_chat_repository = ChatRepository()
_source_provenance_service = SourceProvenanceService()


def _parse_uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def citation_to_response(citation: Citation, filename: str | None) -> ChatCitationResponse:
    return ChatCitationResponse(
        citation_id=str(citation.id),
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


async def load_message_citations(
    db_session: AsyncSession,
    *,
    messages: Sequence[ChatMessage],
    organization_id: UUID,
    decorate: ProvenanceDecorator | None = None,
    repository: ChatRepository | None = None,
    provenance_service: SourceProvenanceService | None = None,
) -> dict[UUID, list[ChatCitationResponse]]:
    """Citations of every assistant message in ``messages``, keyed by message ID.

    One citation query covers all messages. When ``decorate`` is given, source provenance
    for every cited document is loaded with one more query and applied per citation.
    """
    assistant_ids = [message.id for message in messages if message.role == ChatRole.assistant.value]
    repo = repository or _chat_repository
    provenance = provenance_service or _source_provenance_service
    rows_by_message = await repo.list_citations_for_messages_with_filename(
        db_session,
        chat_message_ids=assistant_ids,
    )
    provenance_by_document_id: dict[UUID, Any] = {}
    if decorate is not None and rows_by_message:
        document_ids = list(
            dict.fromkeys(
                citation.document_id for rows in rows_by_message.values() for citation, _ in rows
            )
        )
        provenance_by_document_id = dict(
            await provenance.load_citation_details_for_documents(
                db_session,
                organization_id=organization_id,
                document_ids=document_ids,
            )
        )

    result: dict[UUID, list[ChatCitationResponse]] = {}
    for message_id, rows in rows_by_message.items():
        responses: list[ChatCitationResponse] = []
        for citation, filename in rows:
            response = citation_to_response(citation, filename)
            if decorate is not None:
                response = decorate(response, provenance_by_document_id.get(citation.document_id))
            responses.append(response)
        result[message_id] = responses
    return result


async def persist_answer_citations(
    db_session: AsyncSession,
    *,
    chat_message_id: UUID,
    citations: Sequence[ChatCitationResponse],
    rerank_applied: bool,
    repository: ChatRepository | None = None,
) -> list[ChatCitationResponse]:
    """Insert the answer's citations in one statement.

    Citations whose document or chunk ID is not a UUID are skipped, as before. The returned
    list keeps the input order and carries the persisted ``citation_id`` values.
    """
    kept: list[ChatCitationResponse] = []
    rows: list[CitationInsert] = []
    for citation in citations:
        document_uuid = _parse_uuid_or_none(citation.document_id)
        chunk_uuid = _parse_uuid_or_none(citation.chunk_id)
        if document_uuid is None or chunk_uuid is None:
            continue
        kept.append(citation)
        rows.append(
            CitationInsert(
                document_id=document_uuid,
                chunk_id=chunk_uuid,
                text_snippet=citation.text_snippet or "",
                page_number=citation.page_number,
                start_offset=citation.start_offset,
                end_offset=citation.end_offset,
                similarity_score=citation.similarity_score,
                rerank_score=citation.rerank_score if rerank_applied else None,
            )
        )
    persisted = await (repository or _chat_repository).create_citations_bulk(
        db_session,
        chat_message_id=chat_message_id,
        rows=rows,
    )
    return [
        citation.model_copy(update={"citation_id": str(row.id)})
        for citation, row in zip(kept, persisted, strict=True)
    ]
