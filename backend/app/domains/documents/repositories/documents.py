from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentChunk, DocumentPage
from app.models.enums import DocumentStatus


class DocumentRepository:
    async def create_document(
        self,
        session: AsyncSession,
        *,
        document_id: UUID | None = None,
        organization_id: UUID,
        uploaded_by_user_id: UUID,
        filename: str,
        file_type: str,
        storage_bucket: str,
        storage_object_key: str,
        checksum: str | None = None,
        status: str = DocumentStatus.uploaded.value,
    ) -> Document:
        document_kwargs: dict[str, object] = {
            "organization_id": organization_id,
            "uploaded_by_user_id": uploaded_by_user_id,
            "filename": filename,
            "file_type": file_type,
            "storage_bucket": storage_bucket,
            "storage_object_key": storage_object_key,
            "checksum": checksum,
            "status": status,
        }
        if document_id is not None:
            document_kwargs["id"] = document_id

        document = Document(**document_kwargs)
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

    async def list_documents(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Document]:
        statement = select(Document).where(Document.organization_id == organization_id)
        if status is not None:
            statement = statement.where(Document.status == status)

        sort_columns = {
            "created_at": Document.created_at,
            "updated_at": Document.updated_at,
            "filename": Document.filename,
            "status": Document.status,
        }
        sort_column = sort_columns.get(sort_by, Document.created_at)
        ordered = sort_column.asc() if sort_order == "asc" else sort_column.desc()
        statement = statement.order_by(ordered, Document.id.desc()).offset(offset).limit(limit)

        result = await session.execute(statement)
        return list(result.scalars().all())

    async def count_documents(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
    ) -> int:
        statement = select(func.count(Document.id)).where(Document.organization_id == organization_id)
        if status is not None:
            statement = statement.where(Document.status == status)
        result = await session.execute(statement)
        return int(result.scalar_one())

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

    async def delete_document_pages(self, session: AsyncSession, *, document_id: UUID) -> int:
        result = await session.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        return int(result.rowcount or 0)

    async def list_document_pages(self, session: AsyncSession, *, document_id: UUID) -> list[DocumentPage]:
        result = await session.execute(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number.asc())
        )
        return list(result.scalars().all())

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

    async def delete_document_chunks(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        index_version: str | None = None,
    ) -> int:
        statement = delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        if index_version is not None:
            statement = statement.where(DocumentChunk.index_version == index_version)
        result = await session.execute(statement)
        return int(result.rowcount or 0)

    async def list_document_chunks(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        index_version: str | None = None,
    ) -> list[DocumentChunk]:
        statement = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        if index_version is not None:
            statement = statement.where(DocumentChunk.index_version == index_version)
        result = await session.execute(statement.order_by(DocumentChunk.chunk_index.asc()))
        return list(result.scalars().all())

    async def list_document_chunks_paginated(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        limit: int = 20,
        offset: int = 0,
        index_version: str | None = None,
    ) -> list[DocumentChunk]:
        statement = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        if index_version is not None:
            statement = statement.where(DocumentChunk.index_version == index_version)
        statement = statement.order_by(DocumentChunk.chunk_index.asc()).offset(offset).limit(limit)
        result = await session.execute(statement)
        return list(result.scalars().all())

    async def count_document_chunks(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        index_version: str | None = None,
    ) -> int:
        statement = select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
        if index_version is not None:
            statement = statement.where(DocumentChunk.index_version == index_version)
        result = await session.execute(statement)
        return int(result.scalar_one())
