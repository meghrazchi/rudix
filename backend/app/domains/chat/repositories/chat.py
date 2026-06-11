from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
from app.models.document import Document
from app.models.enums import ChatRole


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
    ) -> list[ChatSession]:
        query = select(ChatSession).where(
            ChatSession.organization_id == organization_id,
            ChatSession.user_id == user_id,
        )
        if search:
            query = query.where(ChatSession.title.ilike(f"%{search}%"))
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
        return result.rowcount > 0

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
    ) -> list[ChatMessage]:
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.chat_session_id == chat_session_id)
            .order_by(
                ChatMessage.created_at.asc(),
                case(
                    (ChatMessage.role == ChatRole.user.value, 0),
                    (ChatMessage.role == ChatRole.assistant.value, 1),
                    else_=2,
                ).asc(),
                ChatMessage.id.asc(),
            )
            .offset(offset)
            .limit(limit)
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
        )
        session.add(message)
        await session.flush()
        await session.refresh(message)
        return message

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
