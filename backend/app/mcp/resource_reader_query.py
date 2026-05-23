from __future__ import annotations

from typing import Any

from app.domains.agents.schemas import ToolErrorCode
from app.mcp.resource_constants import (
    _RESOURCE_DEFAULT_LIMIT,
    _RESOURCE_MAX_LIMIT,
    _RESOURCE_MAX_OFFSET,
    _RESOURCE_MAX_SNIPPET_CHARS,
    _RESOURCE_MAX_TOP_K,
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


async def read_search_context(
    *,
    execute_resource_tool: ResourceToolExecutor,
    query: str,
    status: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    limit: int = _RESOURCE_DEFAULT_LIMIT,
    offset: int = 0,
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
        "documents.search",
        "search_documents",
        {
            "query": coerce_query(query),
            "status": decode_optional_uri_text(status),
            "sort_by": decode_uri_text(sort_by),
            "sort_order": decode_uri_text(sort_order),
            "limit": bounded_limit,
            "offset": bounded_offset,
        },
    )
    if not payload.get("ok"):
        return payload

    data = payload.get("data")
    if not isinstance(data, dict):
        return safe_resource_error_payload(
            resource="documents.search",
            code=ToolErrorCode.internal_error,
            message="Search payload is unavailable.",
        )
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return safe_resource_error_payload(
            resource="documents.search",
            code=ToolErrorCode.internal_error,
            message="Search payload is unavailable.",
        )

    compact_items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        compact_items.append(
            {
                "document_id": item.get("document_id"),
                "filename": truncate_filename(item.get("filename")),
                "status": item.get("status"),
                "chunk_count": item.get("chunk_count"),
                "updated_at": item.get("updated_at"),
            }
        )

    total_value = data.get("total")
    total = total_value if isinstance(total_value, int) else len(compact_items)
    return {
        "ok": True,
        "resource": "documents.search",
        "data": {
            "query": data.get("query"),
            "status": data.get("status"),
            "limit": bounded_limit,
            "offset": bounded_offset,
            "total": total,
            "has_more": bounded_offset + len(compact_items) < total,
            "items": compact_items,
        },
    }


async def read_citations(
    *,
    execute_resource_tool: ResourceToolExecutor,
    query: str,
    document_id: str | None = None,
    top_k: int = 4,
    rerank: bool = True,
) -> dict[str, Any]:
    normalized_document_id = decode_optional_uri_text(document_id)
    bounded_top_k = coerce_bounded_int(
        top_k,
        default=4,
        minimum=1,
        maximum=_RESOURCE_MAX_TOP_K,
    )
    tool_result = await execute_resource_tool(
        "documents.citations",
        "answer_from_context",
        {
            "question": coerce_query(query) or "",
            "document_ids": [normalized_document_id] if normalized_document_id else [],
            "top_k": bounded_top_k,
            "rerank": rerank,
        },
    )
    if not tool_result.get("ok"):
        return tool_result

    data = tool_result.get("data")
    if not isinstance(data, dict):
        return safe_resource_error_payload(
            resource="documents.citations",
            code=ToolErrorCode.internal_error,
            message="Citation payload is unavailable.",
        )

    debug = data.get("debug")
    if not isinstance(debug, dict):
        debug = {}
    raw_citations = data.get("citations")
    citations: list[dict[str, Any]] = []
    if isinstance(raw_citations, list):
        for citation in raw_citations:
            if not isinstance(citation, dict):
                continue
            citations.append(
                {
                    "document_id": citation.get("document_id"),
                    "chunk_id": citation.get("chunk_id"),
                    "filename": truncate_filename(citation.get("filename")),
                    "page_number": citation.get("page_number"),
                    "snippet": truncate_text(
                        citation.get("snippet"),
                        max_length=_RESOURCE_MAX_SNIPPET_CHARS,
                    ),
                    "similarity_score": citation.get("similarity_score"),
                    "rerank_score": citation.get("rerank_score"),
                    "rerank_rank": citation.get("rerank_rank"),
                }
            )

    return {
        "ok": True,
        "resource": "documents.citations",
        "data": {
            "query": coerce_query(query),
            "document_id": normalized_document_id,
            "not_found": data.get("not_found"),
            "confidence": data.get("confidence"),
            "citations": citations,
            "retrieval": {
                "retrieval_count": debug.get("retrieval_count"),
                "selected_count": debug.get("selected_count"),
                "rerank_applied": debug.get("rerank_applied"),
            },
        },
    }
