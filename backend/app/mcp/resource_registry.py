from __future__ import annotations

from typing import Any

from app.mcp.resource_constants import _RESOURCE_DEFAULT_LIMIT
from app.mcp.resource_runtime import MCPResourceRuntime, build_mcp_resource_runtime


def _register_resource(
    server: Any,
    *,
    uri: str,
    handler: Any,
    name: str,
    description: str,
) -> None:
    try:
        server.resource(uri=uri, name=name, description=description)(handler)
        return
    except TypeError:
        pass

    try:
        server.resource(uri, name=name, description=description)(handler)
        return
    except TypeError:
        pass

    server.resource(uri)(handler)


def register_mcp_resources(server: Any, runtime: MCPResourceRuntime | None = None) -> None:
    bound_runtime = runtime or build_mcp_resource_runtime()

    async def documents_resource(
        status: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = _RESOURCE_DEFAULT_LIMIT,
        offset: int = 0,
        query: str | None = None,
    ) -> dict[str, Any]:
        return await bound_runtime.read_documents(
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
            query=query,
        )

    async def document_detail_resource(document_id: str) -> dict[str, Any]:
        return await bound_runtime.read_document_detail(document_id=document_id)

    async def document_status_resource(document_id: str) -> dict[str, Any]:
        return await bound_runtime.read_document_status(document_id=document_id)

    async def document_chunks_resource(
        document_id: str,
        limit: int = _RESOURCE_DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await bound_runtime.read_document_chunks(
            document_id=document_id,
            limit=limit,
            offset=offset,
        )

    async def search_resource(
        query: str,
        status: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int = _RESOURCE_DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        return await bound_runtime.read_search_context(
            query=query,
            status=status,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def citations_resource(
        query: str,
        document_id: str | None = None,
        top_k: int = 4,
        rerank: bool = True,
    ) -> dict[str, Any]:
        return await bound_runtime.read_citations(
            query=query,
            document_id=document_id,
            top_k=top_k,
            rerank=rerank,
        )

    _register_resource(
        server,
        uri="rudix://documents{?status,sort_by,sort_order,limit,offset,query}",
        handler=documents_resource,
        name="documents_list",
        description="List accessible documents with optional query and pagination.",
    )
    _register_resource(
        server,
        uri="rudix://documents/{document_id}",
        handler=document_detail_resource,
        name="document_detail",
        description="Read one accessible document metadata record.",
    )
    _register_resource(
        server,
        uri="rudix://documents/{document_id}/status",
        handler=document_status_resource,
        name="document_status",
        description="Read one accessible document lifecycle status payload.",
    )
    _register_resource(
        server,
        uri="rudix://documents/{document_id}/chunks{?limit,offset}",
        handler=document_chunks_resource,
        name="document_chunks",
        description="Read citation-friendly paginated chunk previews for one document.",
    )
    _register_resource(
        server,
        uri="rudix://search/{query}{?status,sort_by,sort_order,limit,offset}",
        handler=search_resource,
        name="search_documents_context",
        description="Search accessible document metadata and context by query with pagination.",
    )
    _register_resource(
        server,
        uri="rudix://citations/{query}{?document_id,top_k,rerank}",
        handler=citations_resource,
        name="search_citations",
        description="Read citation candidates and confidence metadata for a grounded query.",
    )
