from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domains.agents.schemas import ToolSpec


class _BaseArgsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchDocumentsArgs(_BaseArgsModel):
    query: str | None = Field(default=None, min_length=1, max_length=500)
    status: str | None = Field(default=None, min_length=1, max_length=64)
    sort_by: str = Field(default="updated_at", pattern=r"^(created_at|updated_at|filename|status)$")
    sort_order: str = Field(default="desc", pattern=r"^(asc|desc)$")
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=100_000)


class AskDocumentsArgs(_BaseArgsModel):
    question: str = Field(min_length=1, max_length=8000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=4, ge=1, le=200)
    rerank: bool = True


class GetDocumentChunksArgs(_BaseArgsModel):
    document_id: str = Field(min_length=1, max_length=64)
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=100_000)


class GetDocumentDetailArgs(_BaseArgsModel):
    document_id: str = Field(min_length=1, max_length=64)


class SummarizeArgs(_BaseArgsModel):
    document_id: str = Field(min_length=1, max_length=64)
    top_k: int = Field(default=8, ge=1, le=200)
    rerank: bool = True


class CompareArgs(_BaseArgsModel):
    document_ids: list[str] = Field(min_length=2, max_length=100)
    question: str | None = Field(default=None, min_length=1, max_length=8000)
    top_k: int = Field(default=12, ge=1, le=200)
    rerank: bool = True


@dataclass(frozen=True)
class MCPToolBinding:
    public_name: str
    internal_name: str
    public_spec: ToolSpec
    arguments_model: type[_BaseArgsModel]
    response_transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    deprecated_alias: bool = False

    def normalize_arguments(self, arguments: dict[str, Any] | None) -> dict[str, Any]:
        validated = self.arguments_model.model_validate(arguments or {})
        return validated.model_dump(exclude_none=True)

    def normalize_output(self, output: dict[str, Any] | None) -> dict[str, Any] | None:
        if output is None:
            return None
        if self.response_transform is None:
            return output
        return self.response_transform(output)

    @property
    def arguments_schema(self) -> dict[str, Any]:
        return self.arguments_model.model_json_schema()


def _clone_public_spec(
    *,
    internal_spec: ToolSpec,
    public_name: str,
    description: str | None = None,
) -> ToolSpec:
    payload = internal_spec.model_dump(mode="python")
    payload["name"] = public_name
    if description:
        payload["description"] = description
    return ToolSpec.model_validate(payload)


def _ask_documents_output_transform(output: dict[str, Any]) -> dict[str, Any]:
    answer_text = output.get("response")
    transformed = dict(output)
    transformed["answer"] = answer_text
    return transformed


def build_mcp_tool_bindings(*, internal_specs: tuple[ToolSpec, ...]) -> dict[str, MCPToolBinding]:
    internal_by_name = {spec.name: spec for spec in internal_specs}
    required_internal_names = {
        "search_documents",
        "get_document_detail",
        "list_document_chunks",
        "answer_from_context",
        "summarize_document",
        "compare_documents",
    }
    missing = required_internal_names.difference(internal_by_name.keys())
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"MCP tool bindings missing internal ToolSpec definitions: {missing_list}")

    definitions: list[MCPToolBinding] = [
        MCPToolBinding(
            public_name="search_documents",
            internal_name="search_documents",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["search_documents"],
                public_name="search_documents",
                description=(
                    "Search accessible documents using query/status/sort/pagination filters."
                ),
            ),
            arguments_model=SearchDocumentsArgs,
        ),
        MCPToolBinding(
            public_name="ask_documents",
            internal_name="answer_from_context",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["answer_from_context"],
                public_name="ask_documents",
                description=(
                    "Ask a grounded question across selected documents and return "
                    "answer, citations, and confidence."
                ),
            ),
            arguments_model=AskDocumentsArgs,
            response_transform=_ask_documents_output_transform,
        ),
        MCPToolBinding(
            public_name="get_document_chunks",
            internal_name="list_document_chunks",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["list_document_chunks"],
                public_name="get_document_chunks",
                description="Get paginated chunk previews for one accessible document.",
            ),
            arguments_model=GetDocumentChunksArgs,
        ),
        MCPToolBinding(
            public_name="summarize",
            internal_name="summarize_document",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["summarize_document"],
                public_name="summarize",
                description="Generate a grounded summary for one accessible indexed document.",
            ),
            arguments_model=SummarizeArgs,
        ),
        MCPToolBinding(
            public_name="compare",
            internal_name="compare_documents",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["compare_documents"],
                public_name="compare",
                description="Compare indexed documents and return grounded similarities and differences.",
            ),
            arguments_model=CompareArgs,
        ),
        MCPToolBinding(
            public_name="answer_from_context",
            internal_name="answer_from_context",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["answer_from_context"],
                public_name="answer_from_context",
            ),
            arguments_model=AskDocumentsArgs,
            deprecated_alias=True,
        ),
        MCPToolBinding(
            public_name="list_document_chunks",
            internal_name="list_document_chunks",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["list_document_chunks"],
                public_name="list_document_chunks",
            ),
            arguments_model=GetDocumentChunksArgs,
            deprecated_alias=True,
        ),
        MCPToolBinding(
            public_name="summarize_document",
            internal_name="summarize_document",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["summarize_document"],
                public_name="summarize_document",
            ),
            arguments_model=SummarizeArgs,
            deprecated_alias=True,
        ),
        MCPToolBinding(
            public_name="compare_documents",
            internal_name="compare_documents",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["compare_documents"],
                public_name="compare_documents",
            ),
            arguments_model=CompareArgs,
            deprecated_alias=True,
        ),
        MCPToolBinding(
            public_name="get_document_detail",
            internal_name="get_document_detail",
            public_spec=_clone_public_spec(
                internal_spec=internal_by_name["get_document_detail"],
                public_name="get_document_detail",
            ),
            arguments_model=GetDocumentDetailArgs,
            deprecated_alias=True,
        ),
    ]
    return {binding.public_name: binding for binding in definitions}
