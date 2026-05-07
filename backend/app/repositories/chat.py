from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.models.citation import Citation
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
        similarity_score: float | None = None,
        rerank_score: float | None = None,
    ) -> Citation:
        citation = Citation(
            chat_message_id=chat_message_id,
            document_id=document_id,
            chunk_id=chunk_id,
            text_snippet=text_snippet,
            page_number=page_number,
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
