from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk, DocumentPage
from app.models.enums import DocumentStatus


class DocumentRepository:
    async def create_document(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        uploaded_by_user_id: UUID,
        filename: str,
        file_type: str,
        storage_bucket: str,
        storage_object_key: str,
        status: str = DocumentStatus.uploaded.value,
    ) -> Document:
        document = Document(
            organization_id=organization_id,
            uploaded_by_user_id=uploaded_by_user_id,
            filename=filename,
            file_type=file_type,
            storage_bucket=storage_bucket,
            storage_object_key=storage_object_key,
            status=status,
        )
        session.add(document)
        await session.flush()
        await session.refresh(document)
        return document

    async def get_document(self, session: AsyncSession, *, document_id: UUID, organization_id: UUID) -> Document | None:
        result = await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_document_by_id(self, session: AsyncSession, *, document_id: UUID) -> Document | None:
        result = await session.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def update_document_status(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        status: str,
        error_message: str | None = None,
        page_count: int | None = None,
    ) -> Document | None:
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            return None
        document.status = status
        document.error_message = error_message
        if page_count is not None:
            document.page_count = page_count
        await session.flush()
        await session.refresh(document)
        return document

    async def create_document_page(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        page_number: int,
        text: str,
        char_count: int,
    ) -> DocumentPage:
        page = DocumentPage(
            document_id=document_id,
            page_number=page_number,
            text=text,
            char_count=char_count,
        )
        session.add(page)
        await session.flush()
        await session.refresh(page)
        return page

    async def create_document_chunk(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        chunk_index: int,
        text: str,
        token_count: int,
        embedding_model: str,
        index_version: str = "v1",
        page_number: int | None = None,
        qdrant_point_id: str | None = None,
    ) -> DocumentChunk:
        chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=chunk_index,
            text=text,
            token_count=token_count,
            embedding_model=embedding_model,
            index_version=index_version,
            page_number=page_number,
            qdrant_point_id=qdrant_point_id,
        )
        session.add(chunk)
        await session.flush()
        await session.refresh(chunk)
        return chunk

    async def list_document_chunks(self, session: AsyncSession, *, document_id: UUID) -> list[DocumentChunk]:
        result = await session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index.asc())
        )
        return list(result.scalars().all())
