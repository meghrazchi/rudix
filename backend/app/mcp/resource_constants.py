from __future__ import annotations

_READONLY_RESOURCE_TOOL_NAMES = {
    "search_documents",
    "get_document_detail",
    "list_document_chunks",
    "answer_from_context",
}

_RESOURCE_DEFAULT_LIMIT = 10
_RESOURCE_MAX_LIMIT = 50
_RESOURCE_MAX_OFFSET = 100_000
_RESOURCE_MAX_QUERY_CHARS = 320
_RESOURCE_MAX_SNIPPET_CHARS = 180
_RESOURCE_MAX_FILENAME_CHARS = 120
_RESOURCE_MAX_TOP_K = 10
