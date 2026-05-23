from __future__ import annotations

from app.mcp.resource_reader_documents import (
    read_document_chunks,
    read_document_detail,
    read_document_status,
    read_documents,
)
from app.mcp.resource_reader_query import read_citations, read_search_context
from app.mcp.resource_types import ResourceToolExecutor


class MCPResourceReader:
    """Thin façade that preserves existing runtime imports while delegating by concern."""

    def __init__(self, *, execute_resource_tool: ResourceToolExecutor) -> None:
        self._execute_resource_tool = execute_resource_tool

    async def read_documents(
        self,
        *,
        status: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 10,
        offset: int = 0,
        query: str | None = None,
    ) -> dict[str, object]:
        return await read_documents(
            execute_resource_tool=self._execute_resource_tool,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            query=query,
        )

    async def read_document_detail(self, *, document_id: str) -> dict[str, object]:
        return await read_document_detail(
            execute_resource_tool=self._execute_resource_tool,
            document_id=document_id,
        )

    async def read_document_status(self, *, document_id: str) -> dict[str, object]:
        return await read_document_status(
            execute_resource_tool=self._execute_resource_tool,
            document_id=document_id,
        )

    async def read_document_chunks(
        self,
        *,
        document_id: str,
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, object]:
        return await read_document_chunks(
            execute_resource_tool=self._execute_resource_tool,
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

    async def read_search_context(
        self,
        *,
        query: str,
        status: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = 10,
        offset: int = 0,
    ) -> dict[str, object]:
        return await read_search_context(
            execute_resource_tool=self._execute_resource_tool,
            query=query,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def read_citations(
        self,
        *,
        query: str,
        document_id: str | None = None,
        top_k: int = 4,
        rerank: bool = True,
    ) -> dict[str, object]:
        return await read_citations(
            execute_resource_tool=self._execute_resource_tool,
            query=query,
            document_id=document_id,
            top_k=top_k,
            rerank=rerank,
        )
