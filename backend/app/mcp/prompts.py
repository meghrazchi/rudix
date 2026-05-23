from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.mcp.auth import resolve_mcp_principal
from app.mcp.dependencies import get_http_headers_from_context
from app.mcp.policy import derive_mcp_capabilities
from app.mcp.rate_limit import (
    MCPRateLimiterUnavailableError,
    MCPRateLimitExceededError,
    enforce_mcp_rate_limit,
)


class _PromptArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GroundedQAArgs(_PromptArgs):
    query: str = Field(min_length=1, max_length=8_000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    style: str = Field(default="concise", max_length=120)
    output_format: str = Field(default="markdown", max_length=120)


class SummarizeArgs(_PromptArgs):
    document_id: str = Field(min_length=1, max_length=64)
    focus: str = Field(default="key points, risks, and actions", max_length=400)
    style: str = Field(default="executive", max_length=120)
    output_format: str = Field(default="bullet_points", max_length=120)


class CompareArgs(_PromptArgs):
    document_ids: list[str] = Field(min_length=2, max_length=100)
    comparison_goal: str = Field(
        default="similarities, differences, and contradictions", max_length=400
    )
    style: str = Field(default="analytical", max_length=120)
    output_format: str = Field(default="table_plus_summary", max_length=120)


class ObligationsArgs(_PromptArgs):
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    query: str | None = Field(default=None, min_length=1, max_length=8_000)
    jurisdiction: str | None = Field(default=None, max_length=120)
    output_format: str = Field(default="action_items", max_length=120)


class EvidenceLookupArgs(_PromptArgs):
    claim: str = Field(min_length=1, max_length=8_000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=5, ge=1, le=50)
    output_format: str = Field(default="evidence_list", max_length=120)


@dataclass(frozen=True)
class MCPPromptTemplate:
    name: str
    description: str
    capability: str
    args_model: type[_PromptArgs]
    render: Callable[[BaseModel], str]


def _render_grounded_qa(args: GroundedQAArgs) -> str:
    doc_ids = (
        ", ".join(args.document_ids) if args.document_ids else "all accessible indexed documents"
    )
    return (
        "You are preparing a grounded document answer.\n"
        f"Question: {args.query}\n"
        f"Document scope: {doc_ids}\n"
        f"Style: {args.style}\n"
        f"Output format: {args.output_format}\n\n"
        "Workflow:\n"
        "1. Call `search_documents` to confirm available document scope.\n"
        "2. Call `ask_documents` with `question` and selected `document_ids`.\n"
        "3. Use only citation-grounded facts from returned citations.\n"
        "4. If `not_found=true`, return a safe no-answer message and suggest better query terms.\n"
        "5. Include confidence and key citations in the final response.\n"
        "Do not fabricate sources or unsupported claims."
    )


def _render_summarize(args: SummarizeArgs) -> str:
    return (
        "You are preparing a grounded document summary.\n"
        f"Document ID: {args.document_id}\n"
        f"Focus: {args.focus}\n"
        f"Style: {args.style}\n"
        f"Output format: {args.output_format}\n\n"
        "Workflow:\n"
        "1. Call `get_document_detail` to verify access and lifecycle status.\n"
        "2. Call `summarize` with the same `document_id`.\n"
        "3. Keep summary strictly grounded in returned citations.\n"
        "4. Include confidence, limitations, and follow-up questions if evidence is weak.\n"
        "Do not include policy or legal advice beyond document evidence."
    )


def _render_compare(args: CompareArgs) -> str:
    doc_ids = ", ".join(args.document_ids)
    return (
        "You are preparing a grounded cross-document comparison.\n"
        f"Document IDs: {doc_ids}\n"
        f"Comparison goal: {args.comparison_goal}\n"
        f"Style: {args.style}\n"
        f"Output format: {args.output_format}\n\n"
        "Workflow:\n"
        "1. Call `compare` using provided `document_ids`.\n"
        "2. Organize output into similarities, differences, contradictions, and risks.\n"
        "3. Cite supporting evidence per claim.\n"
        "4. Flag unresolved conflicts as uncertain instead of guessing.\n"
        "Keep conclusions strictly grounded in retrieved evidence."
    )


def _render_obligations(args: ObligationsArgs) -> str:
    doc_scope = (
        ", ".join(args.document_ids) if args.document_ids else "all accessible indexed documents"
    )
    query = args.query or "Find obligations, deadlines, and required follow-up actions."
    jurisdiction = args.jurisdiction or "unspecified"
    return (
        "You are extracting obligations and action items from documents.\n"
        f"Document scope: {doc_scope}\n"
        f"Query intent: {query}\n"
        f"Jurisdiction context: {jurisdiction}\n"
        f"Output format: {args.output_format}\n\n"
        "Workflow:\n"
        "1. Call `ask_documents` with the obligation-focused query.\n"
        "2. Convert grounded findings into action items with owner suggestion, due date, and source citation.\n"
        "3. Mark missing due dates or ambiguous obligations explicitly.\n"
        "4. Never infer legal obligations that are not supported by citations."
    )


def _render_evidence_lookup(args: EvidenceLookupArgs) -> str:
    doc_scope = (
        ", ".join(args.document_ids) if args.document_ids else "all accessible indexed documents"
    )
    return (
        "You are validating a claim using grounded document evidence.\n"
        f"Claim: {args.claim}\n"
        f"Document scope: {doc_scope}\n"
        f"top_k: {args.top_k}\n"
        f"Output format: {args.output_format}\n\n"
        "Workflow:\n"
        "1. Call `ask_documents` with the claim rewritten as a verification question.\n"
        "2. Extract supporting and contradicting citations separately.\n"
        "3. Provide a final verdict: supported, contradicted, or insufficient evidence.\n"
        "4. Include confidence and exact citation snippets.\n"
        "Do not claim verification without citation support."
    )


def _build_templates() -> dict[str, MCPPromptTemplate]:
    templates = [
        MCPPromptTemplate(
            name="grounded_qa",
            description="Grounded document Q&A workflow prompt template.",
            capability="documents.read",
            args_model=GroundedQAArgs,
            render=lambda args: _render_grounded_qa(args),  # type: ignore[arg-type]
        ),
        MCPPromptTemplate(
            name="summarize_workflow",
            description="Grounded document summarization workflow prompt template.",
            capability="documents.summary.read",
            args_model=SummarizeArgs,
            render=lambda args: _render_summarize(args),  # type: ignore[arg-type]
        ),
        MCPPromptTemplate(
            name="compare_workflow",
            description="Grounded document comparison workflow prompt template.",
            capability="documents.compare.read",
            args_model=CompareArgs,
            render=lambda args: _render_compare(args),  # type: ignore[arg-type]
        ),
        MCPPromptTemplate(
            name="obligations_action_items",
            description="Obligation and action-item extraction workflow prompt template.",
            capability="chat.answer",
            args_model=ObligationsArgs,
            render=lambda args: _render_obligations(args),  # type: ignore[arg-type]
        ),
        MCPPromptTemplate(
            name="evidence_lookup",
            description="Evidence lookup and claim verification workflow prompt template.",
            capability="chat.answer",
            args_model=EvidenceLookupArgs,
            render=lambda args: _render_evidence_lookup(args),  # type: ignore[arg-type]
        ),
    ]
    return {template.name: template for template in templates}


class MCPPromptRuntime:
    def __init__(self) -> None:
        self._templates = _build_templates()

    @property
    def templates(self) -> dict[str, MCPPromptTemplate]:
        return self._templates

    async def _resolve_authorized_principal(
        self, *, capability: str, prompt_name: str
    ) -> AuthenticatedPrincipal:
        if not settings.feature_enable_mcp:
            raise RuntimeError("MCP is disabled for this deployment.")
        try:
            principal = await resolve_mcp_principal(get_http_headers_from_context())
        except AuthenticationError as exc:
            raise AuthenticationError("Authentication failed for MCP prompt request.") from exc
        except AuthorizationError as exc:
            raise AuthorizationError("MCP principal is not authorized for this prompt.") from exc

        if principal.organization_id is None:
            raise AuthorizationError("No active organization context for principal.")

        capabilities = derive_mcp_capabilities(principal)
        if capability.strip().lower() not in capabilities:
            raise AuthorizationError("MCP principal capability is not authorized for this prompt.")

        try:
            await enforce_mcp_rate_limit(principal=principal, tool_name=f"prompt:{prompt_name}")
        except MCPRateLimitExceededError as exc:
            raise RuntimeError("MCP rate limit exceeded. Retry later.") from exc
        except MCPRateLimiterUnavailableError as exc:
            raise RuntimeError("MCP rate limiter unavailable for this deployment.") from exc

        return principal

    async def build_prompt(
        self, *, prompt_name: str, arguments: dict[str, Any] | None = None
    ) -> str:
        template = self._templates.get(prompt_name)
        if template is None:
            raise ValueError("Prompt template is not registered for this MCP server.")

        await self._resolve_authorized_principal(
            capability=template.capability,
            prompt_name=template.name,
        )

        try:
            validated = template.args_model.model_validate(arguments or {})
        except ValidationError as exc:
            raise ValueError("Prompt arguments failed validation.") from exc
        return template.render(validated)


def _register_prompt(
    server: Any,
    *,
    name: str,
    description: str,
    handler: Any,
) -> None:
    try:
        server.prompt(name=name, description=description)(handler)
        return
    except TypeError:
        pass

    try:
        server.prompt(name, description=description)(handler)
        return
    except TypeError:
        pass

    try:
        server.prompt(name=name)(handler)
        return
    except TypeError:
        pass

    server.prompt(name)(handler)


@lru_cache(maxsize=1)
def build_mcp_prompt_runtime() -> MCPPromptRuntime:
    return MCPPromptRuntime()


def register_mcp_prompts(server: Any, runtime: MCPPromptRuntime | None = None) -> None:
    bound_runtime = runtime or build_mcp_prompt_runtime()

    for template in bound_runtime.templates.values():
        prompt_name = template.name
        prompt_description = template.description

        async def prompt_handler(
            arguments: dict[str, Any] | None = None, *, _prompt_name: str = prompt_name
        ) -> str:
            return await bound_runtime.build_prompt(prompt_name=_prompt_name, arguments=arguments)

        prompt_handler.__name__ = f"prompt_{prompt_name}"
        prompt_handler.__doc__ = (
            f"{prompt_description}\n\nProvide prompt parameters in the `arguments` object."
        )
        _register_prompt(
            server,
            name=prompt_name,
            description=prompt_description,
            handler=prompt_handler,
        )
