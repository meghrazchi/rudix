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
        source: str | None = None,
        language: str | None = None,
        retention_class: str | None = None,
        notes: str | None = None,
        tags: str | None = None,
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
            "source": source,
            "language": language,
            "retention_class": retention_class,
            "notes": notes,
            "tags": tags,
        }
        if document_id is not None:
            document_kwargs["id"] = document_id

        document = Document(**document_kwargs)
        session.add(document)
        await session.flush()
        await session.refresh(document)
        return document

    async def get_document(
        self, session: AsyncSession, *, document_id: UUID, organization_id: UUID
    ) -> Document | None:
        result = await session.execute(
            select(Document).where(
                Document.id == document_id,
                Document.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_document_by_id(
        self, session: AsyncSession, *, document_id: UUID
    ) -> Document | None:
        result = await session.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        status: str | None = None,
        file_type: str | None = None,
        filename_query: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> list[Document]:
        statement = select(Document).where(Document.organization_id == organization_id)
        if status is not None:
            statement = statement.where(Document.status == status)
        if file_type is not None:
            statement = statement.where(Document.file_type == file_type)
        if filename_query is not None:
            normalized_query = filename_query.strip()
            if normalized_query:
                statement = statement.where(Document.filename.ilike(f"%{normalized_query}%"))

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
        file_type: str | None = None,
        filename_query: str | None = None,
    ) -> int:
        statement = select(func.count(Document.id)).where(
            Document.organization_id == organization_id
        )
        if status is not None:
            statement = statement.where(Document.status == status)
        if file_type is not None:
            statement = statement.where(Document.file_type == file_type)
        if filename_query is not None:
            normalized_query = filename_query.strip()
            if normalized_query:
                statement = statement.where(Document.filename.ilike(f"%{normalized_query}%"))
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
        chunk_count: int | None = None,
        chunking_strategy: str | None = None,
        chunking_profile_version: str | None = None,
        chunking_config_snapshot: dict | None = None,
    ) -> Document | None:
        result = await session.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if document is None:
            return None
        document.status = status
        document.error_message = error_message
        if page_count is not None:
            document.page_count = page_count
        if chunk_count is not None:
            document.chunk_count = chunk_count
        if chunking_strategy is not None:
            document.chunking_strategy = chunking_strategy
        if chunking_profile_version is not None:
            document.chunking_profile_version = chunking_profile_version
        if chunking_config_snapshot is not None:
            document.chunking_config_snapshot = chunking_config_snapshot
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
        result = await session.execute(
            delete(DocumentPage).where(DocumentPage.document_id == document_id)
        )
        return int(result.rowcount or 0)

    async def list_document_pages(
        self, session: AsyncSession, *, document_id: UUID
    ) -> list[DocumentPage]:
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
        chunk_hash: str | None = None,
        section_path: str | None = None,
        language: str | None = None,
        source_start_offset: int | None = None,
        source_end_offset: int | None = None,
        parent_chunk_id: UUID | None = None,
        chunk_level: int | None = None,
        child_count: int | None = None,
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
            chunk_hash=chunk_hash,
            section_path=section_path,
            language=language,
            source_start_offset=source_start_offset,
            source_end_offset=source_end_offset,
            parent_chunk_id=parent_chunk_id,
            chunk_level=chunk_level,
            child_count=child_count,
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
        statement = select(func.count(DocumentChunk.id)).where(
            DocumentChunk.document_id == document_id
        )
        if index_version is not None:
            statement = statement.where(DocumentChunk.index_version == index_version)
        result = await session.execute(statement)
        return int(result.scalar_one())

    async def get_document_chunk_token_distribution(
        self,
        session: AsyncSession,
        *,
        document_id: UUID,
        index_version: str | None = None,
    ) -> dict[str, int | float] | None:
        statement = select(
            func.min(DocumentChunk.token_count),
            func.max(DocumentChunk.token_count),
            func.avg(DocumentChunk.token_count),
            func.sum(DocumentChunk.token_count),
        ).where(DocumentChunk.document_id == document_id)
        if index_version is not None:
            statement = statement.where(DocumentChunk.index_version == index_version)

        result = await session.execute(statement)
        min_tokens, max_tokens, avg_tokens, total_tokens = result.one()
        if min_tokens is None or max_tokens is None or avg_tokens is None or total_tokens is None:
            return None

        return {
            "min_tokens": int(min_tokens),
            "max_tokens": int(max_tokens),
            "avg_tokens": round(float(avg_tokens), 1),
            "total_tokens": int(total_tokens),
        }
