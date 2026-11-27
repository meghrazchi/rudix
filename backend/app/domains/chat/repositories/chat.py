from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.document import Document
from app.models.enums import ChatRole
from app.shared.pagination import CursorValue, KeysetColumn, apply_keyset

SESSION_SORT_NAME = "chat_sessions.updated_at.desc"
MESSAGE_SORT_NAME = "chat_messages.created_at.asc"
SESSION_SORT_COLUMNS = (ChatSession.updated_at, ChatSession.id)
_ROLE_RANK = {ChatRole.user.value: 0, ChatRole.assistant.value: 1}


def _message_sort_columns() -> tuple[KeysetColumn, KeysetColumn, KeysetColumn]:
    role_rank = case(
        (ChatMessage.role == ChatRole.user.value, 0),
        (ChatMessage.role == ChatRole.assistant.value, 1),
        else_=2,
    )
    return (ChatMessage.created_at, role_rank, ChatMessage.id)


def session_sort_key(chat_session: ChatSession) -> list[CursorValue]:
    return [chat_session.updated_at, chat_session.id]


def message_sort_key(message: ChatMessage) -> list[CursorValue]:
    """``(created_at, role rank, id)``: user before assistant within one timestamp."""
    return [message.created_at, _ROLE_RANK.get(message.role, 2), message.id]


class ChatRepository:
    async def create_chat_session(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        title: str | None = None,
    ) -> ChatSession:
        chat_session = ChatSession(
            organization_id=organization_id,
            user_id=user_id,
            title=title,
        )
        session.add(chat_session)
        await session.flush()
        await session.refresh(chat_session)
        return chat_session

    async def get_chat_session(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> ChatSession | None:
        result = await session.execute(
            select(ChatSession).where(
                ChatSession.id == chat_session_id,
                ChatSession.organization_id == organization_id,
                ChatSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_chat_sessions(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
        search: str | None = None,
        keyset: Sequence[CursorValue] | None = None,
    ) -> list[ChatSession]:
        """List a user's sessions, newest activity first.

        ``keyset`` is ``(updated_at, id)`` of the previous page's last row. Sessions updated
        between pages move to the top, so a cursor walk can miss or repeat them.
        """
        query = select(ChatSession).where(
            ChatSession.organization_id == organization_id,
            ChatSession.user_id == user_id,
        )
        if search:
            query = query.where(ChatSession.title.ilike(f"%{search}%"))
        if keyset is not None:
            query = apply_keyset(query, SESSION_SORT_COLUMNS, True, keyset)
        query = (
            query.order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(query)
        return list(result.scalars().all())

    async def count_chat_sessions(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
        search: str | None = None,
    ) -> int:
        query = select(func.count(ChatSession.id)).where(
            ChatSession.organization_id == organization_id,
            ChatSession.user_id == user_id,
        )
        if search:
            query = query.where(ChatSession.title.ilike(f"%{search}%"))
        result = await session.execute(query)
        return int(result.scalar_one())

    async def update_chat_session_title(
        self,
        session: AsyncSession,
        *,
        chat_session: ChatSession,
        title: str | None,
    ) -> ChatSession:
        chat_session.title = title
        session.add(chat_session)
        await session.flush()
        await session.refresh(chat_session)
        return chat_session

    async def delete_chat_session(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        result = await session.execute(
            delete(ChatSession).where(
                ChatSession.id == chat_session_id,
                ChatSession.organization_id == organization_id,
                ChatSession.user_id == user_id,
            )
        )
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def count_messages_by_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: list[UUID],
    ) -> dict[UUID, int]:
        if not session_ids:
            return {}

        result = await session.execute(
            select(ChatMessage.chat_session_id, func.count(ChatMessage.id))
            .where(ChatMessage.chat_session_id.in_(session_ids))
            .group_by(ChatMessage.chat_session_id)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def list_chat_messages(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
        limit: int = 200,
        offset: int = 0,
        keyset: Sequence[CursorValue] | None = None,
    ) -> list[ChatMessage]:
        """Messages in conversation order; ``keyset`` is ``message_sort_key`` of the last row."""
        columns = _message_sort_columns()
        query = select(ChatMessage).where(ChatMessage.chat_session_id == chat_session_id)
        if keyset is not None:
            query = apply_keyset(query, columns, False, keyset)
        result = await session.execute(
            query.order_by(*(column.asc() for column in columns)).offset(offset).limit(limit)
        )
        return list(result.scalars().all())

    async def count_chat_messages(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
    ) -> int:
        result = await session.execute(
            select(func.count(ChatMessage.id)).where(ChatMessage.chat_session_id == chat_session_id)
        )
        return int(result.scalar_one())

    async def count_user_questions(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> int:
        session_ids_subquery = (
            select(ChatSession.id)
            .where(
                ChatSession.organization_id == organization_id,
                ChatSession.user_id == user_id,
            )
            .scalar_subquery()
        )
        result = await session.execute(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.chat_session_id.in_(session_ids_subquery),
                ChatMessage.role == ChatRole.user.value,
            )
        )
        return int(result.scalar_one())

    async def create_chat_message(
        self,
        session: AsyncSession,
        *,
        chat_session_id: UUID,
        content: str,
        role: str = ChatRole.user.value,
        confidence_score: float | None = None,
        latency_ms: int | None = None,
        model_name: str | None = None,
        token_input_count: int | None = None,
        token_output_count: int | None = None,
        cost_usd: Decimal | None = None,
        prompt_template_version_id: UUID | None = None,
        trust_metadata_json: dict | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            chat_session_id=chat_session_id,
            role=role,
            content=content,
            confidence_score=confidence_score,
            latency_ms=latency_ms,
            model_name=model_name,
            token_input_count=token_input_count,
            token_output_count=token_output_count,
            cost_usd=cost_usd,
            prompt_template_version_id=prompt_template_version_id,
            trust_metadata_json=trust_metadata_json,
        )
        session.add(message)
        await session.flush()
        await session.refresh(message)
        return message

    async def get_message_for_user(
        self,
        session: AsyncSession,
        *,
        message_id: UUID,
        organization_id: UUID,
        user_id: UUID,
    ) -> ChatMessage | None:
        result = await session.execute(
            select(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.chat_session_id)
            .where(
                ChatMessage.id == message_id,
                ChatSession.organization_id == organization_id,
                ChatSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_citation(
        self,
        session: AsyncSession,
        *,
        chat_message_id: UUID,
        document_id: UUID,
        chunk_id: UUID,
        text_snippet: str,
        page_number: int | None = None,
        start_offset: int | None = None,
        end_offset: int | None = None,
        similarity_score: float | None = None,
        rerank_score: float | None = None,
    ) -> Citation:
        citation = Citation(
            chat_message_id=chat_message_id,
            document_id=document_id,
            chunk_id=chunk_id,
            text_snippet=text_snippet,
            page_number=page_number,
            start_offset=start_offset,
            end_offset=end_offset,
            similarity_score=similarity_score,
            rerank_score=rerank_score,
        )
        session.add(citation)
        await session.flush()
        await session.refresh(citation)
        return citation

    async def get_citation_for_document(
        self,
        session: AsyncSession,
        *,
        citation_id: UUID,
        document_id: UUID,
    ) -> Citation | None:
        result = await session.execute(
            select(Citation)
            .where(
                Citation.id == citation_id,
                Citation.document_id == document_id,
            )
            .order_by(Citation.created_at.asc())
        )
        return result.scalar_one_or_none()

    async def list_citations_for_message(
        self,
        session: AsyncSession,
        *,
        chat_message_id: UUID,
    ) -> list[Citation]:
        result = await session.execute(
            select(Citation)
            .where(Citation.chat_message_id == chat_message_id)
            .order_by(Citation.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_citations_for_message_with_filename(
        self,
        session: AsyncSession,
        *,
        chat_message_id: UUID,
    ) -> list[tuple[Citation, str | None]]:
        result = await session.execute(
            select(Citation, Document.filename)
            .join(Document, Document.id == Citation.document_id)
            .where(Citation.chat_message_id == chat_message_id)
            .order_by(Citation.created_at.asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    async def list_citations_for_messages_with_filename(
        self,
        session: AsyncSession,
        *,
        chat_message_ids: list[UUID],
    ) -> dict[UUID, list[tuple[Citation, str | None]]]:
        """Citations with document filenames for many messages in one ``IN`` query.

        Rows are grouped by message in ``(created_at, id)`` order; messages without
        citations are absent from the result.
        """
        if not chat_message_ids:
            return {}
        result = await session.execute(
            select(Citation, Document.filename)
            .join(Document, Document.id == Citation.document_id)
            .where(Citation.chat_message_id.in_(chat_message_ids))
            .order_by(Citation.chat_message_id, Citation.created_at.asc(), Citation.id.asc())
        )
        grouped: dict[UUID, list[tuple[Citation, str | None]]] = {}
        for citation, filename in result.all():
            grouped.setdefault(citation.chat_message_id, []).append((citation, filename))
        return grouped

    async def create_citations_bulk(
        self,
        session: AsyncSession,
        *,
        chat_message_id: UUID,
        rows: Sequence[CitationInsert],
    ) -> list[Citation]:
        """Insert all citations of one answer with a single flush and no refresh.

        IDs are generated client side. All rows share one ``created_at`` (the transaction
        time), so the IDs are assigned in ascending order: reading back by
        ``(created_at, id)`` returns the citations in the order they were given.
        """
        if not rows:
            return []
        ids = sorted(uuid4() for _ in rows)
        citations = [
            Citation(
                id=citation_id,
                chat_message_id=chat_message_id,
                document_id=row.document_id,
                chunk_id=row.chunk_id,
                text_snippet=row.text_snippet,
                page_number=row.page_number,
                start_offset=row.start_offset,
                end_offset=row.end_offset,
                similarity_score=row.similarity_score,
                rerank_score=row.rerank_score,
            )
            for citation_id, row in zip(ids, rows, strict=True)
        ]
        session.add_all(citations)
        await session.flush()
        return citations


@dataclass(frozen=True)
class CitationInsert:
    """One citation row for ``ChatRepository.create_citations_bulk``."""

    document_id: UUID
    chunk_id: UUID
    text_snippet: str
    page_number: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    similarity_score: float | None = None
    rerank_score: float | None = None
