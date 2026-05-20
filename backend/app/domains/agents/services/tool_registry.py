from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.auth.models import AuthenticatedPrincipal
from app.domains.agents.schemas import (
    ToolBudget,
    ToolCall,
    ToolEffectPolicy,
    ToolRedactionPolicy,
    ToolSpec,
    ToolSurface,
)
from app.models.enums import OrganizationRole

ToolHandler = Callable[
    [ToolCall, AuthenticatedPrincipal],
    Awaitable[dict[str, Any] | None] | dict[str, Any] | None,
]


@dataclass(frozen=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    """Typed allowlist registry for internal agent tool execution."""

    def __init__(self, *, specs: tuple[ToolSpec, ...] | None = None) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}
        if specs:
            for spec in specs:
                self.register_spec(spec)

    def register_spec(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"Duplicate tool spec registration: {spec.name}")
        self._specs[spec.name] = spec

    def register_handler(self, *, tool_name: str, handler: ToolHandler) -> None:
        if tool_name not in self._specs:
            raise ValueError(f"Tool handler registered for unknown spec: {tool_name}")
        if tool_name in self._handlers:
            raise ValueError(f"Duplicate tool handler registration: {tool_name}")
        self._handlers[tool_name] = handler

    def register_tool(self, *, spec: ToolSpec, handler: ToolHandler) -> None:
        self.register_spec(spec)
        self.register_handler(tool_name=spec.name, handler=handler)

    def get_spec(self, tool_name: str) -> ToolSpec | None:
        return self._specs.get(tool_name)

    def get_handler(self, tool_name: str) -> ToolHandler | None:
        return self._handlers.get(tool_name)

    def resolve(self, tool_name: str) -> RegisteredTool | None:
        spec = self.get_spec(tool_name)
        handler = self.get_handler(tool_name)
        if spec is None or handler is None:
            return None
        return RegisteredTool(spec=spec, handler=handler)

    def is_allowed(self, tool_name: str) -> bool:
        return tool_name in self._specs

    def list_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._specs.values())

    def list_tool_names(self) -> tuple[str, ...]:
        return tuple(self._specs.keys())


def build_default_tool_specs(
    *,
    max_calls_per_run: int = 30,
    max_input_bytes: int = 32_768,
    max_output_bytes: int = 65_536,
    timeout_ms: int = 8_000,
) -> tuple[ToolSpec, ...]:
    read_budget = ToolBudget(
        max_calls_per_run=max_calls_per_run,
        max_input_bytes=max_input_bytes,
        max_output_bytes=max_output_bytes,
        timeout_ms=timeout_ms,
        max_retry_attempts=1,
    )
    write_budget = ToolBudget(
        max_calls_per_run=max_calls_per_run,
        max_input_bytes=max_input_bytes,
        max_output_bytes=max_output_bytes,
        timeout_ms=timeout_ms,
        max_retry_attempts=0,
    )
    default_redaction = ToolRedactionPolicy(
        input_keys=["authorization", "token", "password", "prompt", "question", "document_body"],
        output_keys=["authorization", "token", "password", "content", "text", "answer"],
    )

    return (
        ToolSpec(
            name="documents.list",
            description="List accessible documents for the active organization context.",
            capability="documents.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="documents.get",
            description="Read document metadata and lifecycle status for one document.",
            capability="documents.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="documents.chunks.list",
            description="List chunk previews or full text for a document using pagination controls.",
            capability="documents.chunks.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="search_documents",
            description="Search accessible documents by status, filename query, and pagination controls.",
            capability="documents.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="get_document_detail",
            description="Get one accessible document detail record with lifecycle metadata.",
            capability="documents.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="list_document_chunks",
            description="List paginated chunk previews for one accessible indexed document.",
            capability="documents.chunks.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="answer_from_context",
            description="Produce a grounded answer with citations and confidence from accessible documents.",
            capability="chat.answer",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="summarize_document",
            description="Generate a grounded summary for one accessible indexed document.",
            capability="documents.summary.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="compare_documents",
            description="Compare accessible indexed documents and return grounded similarities and differences.",
            capability="documents.compare.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="chat.answer",
            description="Run a grounded chat answer query and return citations and confidence.",
            capability="chat.answer",
            effect_policy=ToolEffectPolicy.side_effect,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api],
            budget=write_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="evaluations.run",
            description="Queue an evaluation run for an evaluation set with a retrieval configuration.",
            capability="evaluations.run",
            effect_policy=ToolEffectPolicy.side_effect,
            required_roles=[OrganizationRole.owner.value, OrganizationRole.admin.value],
            approval_required=True,
            surfaces=[ToolSurface.api],
            budget=write_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="pipeline.runs.get",
            description="Read pipeline run and node details for observability and debugging.",
            capability="pipeline.read",
            effect_policy=ToolEffectPolicy.read_only,
            required_roles=[role.value for role in OrganizationRole],
            surfaces=[ToolSurface.api, ToolSurface.mcp],
            budget=read_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="documents.reindex",
            description="Queue a document re-index action for owner and admin roles.",
            capability="documents.reindex",
            effect_policy=ToolEffectPolicy.side_effect,
            required_roles=[OrganizationRole.owner.value, OrganizationRole.admin.value],
            approval_required=True,
            surfaces=[ToolSurface.api],
            budget=write_budget,
            redaction=default_redaction,
        ),
        ToolSpec(
            name="documents.delete",
            description="Delete a document and dependent retrieval artifacts for owner and admin roles.",
            capability="documents.delete",
            effect_policy=ToolEffectPolicy.side_effect,
            required_roles=[OrganizationRole.owner.value, OrganizationRole.admin.value],
            approval_required=True,
            surfaces=[ToolSurface.api],
            budget=write_budget,
            redaction=default_redaction,
        ),
    )
