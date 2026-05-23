from __future__ import annotations

from typing import Any

from app.domains.agents.schemas import ToolErrorCode
from app.mcp.resource_constants import (
    _RESOURCE_DEFAULT_LIMIT,
    _RESOURCE_MAX_LIMIT,
    _RESOURCE_MAX_OFFSET,
    _RESOURCE_MAX_SNIPPET_CHARS,
)
from app.mcp.resource_types import ResourceToolExecutor
from app.mcp.resource_utils import (
    coerce_bounded_int,
    coerce_query,
    decode_optional_uri_text,
    decode_uri_text,
    safe_resource_error_payload,
    truncate_filename,
    truncate_text,
)


async def read_documents(
    *,
    execute_resource_tool: ResourceToolExecutor,
    status: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    limit: int = _RESOURCE_DEFAULT_LIMIT,
    offset: int = 0,
    query: str | None = None,
) -> dict[str, Any]:
    bounded_limit = coerce_bounded_int(
        limit,
        default=_RESOURCE_DEFAULT_LIMIT,
        minimum=1,
        maximum=_RESOURCE_MAX_LIMIT,
    )
    bounded_offset = coerce_bounded_int(
        offset,
        default=0,
        minimum=0,
        maximum=_RESOURCE_MAX_OFFSET,
    )
    payload = await execute_resource_tool(
        "documents.list",
        "search_documents",
        {
            "status": decode_optional_uri_text(status),
            "sort_by": decode_uri_text(sort_by),
            "sort_order": decode_uri_text(sort_order),
            "limit": bounded_limit,
            "offset": bounded_offset,
            "query": coerce_query(query),
        },
    )
    if not payload.get("ok"):
        return payload

    data = payload.get("data")
    if not isinstance(data, dict):
        return safe_resource_error_payload(
            resource="documents.list",
            code=ToolErrorCode.internal_error,
            message="Document list payload is unavailable.",
        )
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return safe_resource_error_payload(
            resource="documents.list",
            code=ToolErrorCode.internal_error,
            message="Document list payload is unavailable.",
        )

    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "document_id": item.get("document_id"),
                "filename": truncate_filename(item.get("filename")),
                "file_type": item.get("file_type"),
                "status": item.get("status"),
                "page_count": item.get("page_count"),
                "chunk_count": item.get("chunk_count"),
                "updated_at": item.get("updated_at"),
            }
        )

    total_value = data.get("total")
    total = total_value if isinstance(total_value, int) else len(items)
    return {
        "ok": True,
        "resource": "documents.list",
        "data": {
            "query": data.get("query"),
            "status": data.get("status"),
            "sort_by": data.get("sort_by"),
            "sort_order": data.get("sort_order"),
            "limit": bounded_limit,
            "offset": bounded_offset,
            "total": total,
            "has_more": bounded_offset + len(items) < total,
            "items": items,
        },
    }


async def read_document_detail(
    *,
    execute_resource_tool: ResourceToolExecutor,
    document_id: str,
) -> dict[str, Any]:
    return await execute_resource_tool(
        "documents.detail",
        "get_document_detail",
        {"document_id": decode_uri_text(document_id)},
    )


async def read_document_status(
    *,
    execute_resource_tool: ResourceToolExecutor,
    document_id: str,
) -> dict[str, Any]:
    detail = await read_document_detail(
        execute_resource_tool=execute_resource_tool,
        document_id=document_id,
    )
    if not detail.get("ok"):
        return detail

    data = detail.get("data")
    if not isinstance(data, dict):
        return safe_resource_error_payload(
            resource="documents.status",
            code=ToolErrorCode.internal_error,
            message="Document status payload is unavailable.",
        )
    document = data.get("document")
    if not isinstance(document, dict):
        return safe_resource_error_payload(
            resource="documents.status",
            code=ToolErrorCode.internal_error,
            message="Document status payload is unavailable.",
        )

    return {
        "ok": True,
        "resource": "documents.status",
        "data": {
            "document_id": document.get("document_id"),
            "filename": document.get("filename"),
            "status": document.get("status"),
            "error_message": document.get("error_message"),
            "error_details": document.get("error_details"),
            "created_at": document.get("created_at"),
            "updated_at": document.get("updated_at"),
        },
    }


async def read_document_chunks(
    *,
    execute_resource_tool: ResourceToolExecutor,
    document_id: str,
    limit: int = _RESOURCE_DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    detail = await read_document_detail(
        execute_resource_tool=execute_resource_tool,
        document_id=document_id,
    )
    if not detail.get("ok"):
        return detail

    detail_data = detail.get("data")
    if not isinstance(detail_data, dict):
        return safe_resource_error_payload(
            resource="documents.chunks",
            code=ToolErrorCode.internal_error,
            message="Document detail payload is unavailable.",
        )
    document = detail_data.get("document")
    if not isinstance(document, dict):
        return safe_resource_error_payload(
            resource="documents.chunks",
            code=ToolErrorCode.internal_error,
            message="Document detail payload is unavailable.",
        )

    bounded_limit = coerce_bounded_int(
        limit,
        default=_RESOURCE_DEFAULT_LIMIT,
        minimum=1,
        maximum=_RESOURCE_MAX_LIMIT,
    )
    bounded_offset = coerce_bounded_int(
        offset,
        default=0,
        minimum=0,
        maximum=_RESOURCE_MAX_OFFSET,
    )
    chunks = await execute_resource_tool(
        "documents.chunks",
        "list_document_chunks",
        {
            "document_id": decode_uri_text(document_id),
            "limit": bounded_limit,
            "offset": bounded_offset,
        },
    )
    if not chunks.get("ok"):
        return chunks

    chunks_data = chunks.get("data")
    if not isinstance(chunks_data, dict):
        return safe_resource_error_payload(
            resource="documents.chunks",
            code=ToolErrorCode.internal_error,
            message="Document chunk payload is unavailable.",
        )

    items = chunks_data.get("items")
    if not isinstance(items, list):
        return safe_resource_error_payload(
            resource="documents.chunks",
            code=ToolErrorCode.internal_error,
            message="Document chunk payload is unavailable.",
        )

    citation_items: list[dict[str, Any]] = []
    for chunk in items:
        if not isinstance(chunk, dict):
            continue
        preview = truncate_text(chunk.get("preview"), max_length=_RESOURCE_MAX_SNIPPET_CHARS)
        citation_items.append(
            {
                "chunk_id": chunk.get("chunk_id"),
                "chunk_index": chunk.get("chunk_index"),
                "page_number": chunk.get("page_number"),
                "token_count": chunk.get("token_count"),
                "preview": preview,
                "embedding_model": chunk.get("embedding_model"),
                "index_version": chunk.get("index_version"),
                "created_at": chunk.get("created_at"),
                "citation": {
                    "document_id": chunks_data.get("document_id"),
                    "filename": truncate_filename(document.get("filename")),
                    "page_number": chunk.get("page_number"),
                    "chunk_id": chunk.get("chunk_id"),
                    "snippet": preview,
                },
            }
        )

    return {
        "ok": True,
        "resource": "documents.chunks",
        "data": {
            "document_id": chunks_data.get("document_id"),
            "filename": truncate_filename(document.get("filename")),
            "status": chunks_data.get("status"),
            "limit": bounded_limit,
            "offset": bounded_offset,
            "total": chunks_data.get("total"),
            "items": citation_items,
        },
    }
