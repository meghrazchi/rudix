from __future__ import annotations

from app.domains.agents.schemas import (
    ToolBudget,
    ToolEffectPolicy,
    ToolRedactionPolicy,
    ToolSpec,
    ToolSurface,
)
from app.models.enums import OrganizationRole


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
            surfaces=[ToolSurface.api],
            budget=write_budget,
            redaction=default_redaction,
        ),
    )

