from __future__ import annotations

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.domains.agents.schemas import ToolCall, ToolEffectPolicy, ToolSpec, ToolSurface
from app.domains.agents.services import ToolRegistry, build_default_tool_specs


async def _handler(call: ToolCall, principal: AuthenticatedPrincipal) -> dict[str, object]:
    del call, principal
    return {"status": "ok"}


def test_tool_registry_allowlist_and_resolution() -> None:
    spec = ToolSpec(
        name="documents.list",
        description="List all documents that are visible in the organization scope.",
        capability="documents.read",
        effect_policy=ToolEffectPolicy.read_only,
        required_roles=["viewer"],
        surfaces=[ToolSurface.api, ToolSurface.mcp],
    )
    registry = ToolRegistry()
    registry.register_tool(spec=spec, handler=_handler)

    assert registry.is_allowed("documents.list") is True
    assert registry.is_allowed("documents.delete") is False
    assert registry.get_spec("documents.list") is not None
    assert registry.get_handler("documents.list") is not None
    resolved = registry.resolve("documents.list")
    assert resolved is not None
    assert resolved.spec.name == "documents.list"


def test_tool_registry_rejects_duplicate_spec_and_unknown_handler_registration() -> None:
    spec = ToolSpec(
        name="documents.get",
        description="Read one document metadata record in the active organization.",
        capability="documents.read",
        effect_policy=ToolEffectPolicy.read_only,
        required_roles=["viewer"],
        surfaces=[ToolSurface.api],
    )
    registry = ToolRegistry(specs=(spec,))

    with pytest.raises(ValueError, match="Duplicate tool spec registration"):
        registry.register_spec(spec)

    with pytest.raises(ValueError, match="unknown spec"):
        registry.register_handler(tool_name="documents.list", handler=_handler)


def test_default_tool_specs_include_approval_required_side_effect_tools() -> None:
    specs = build_default_tool_specs()
    approval_required_tools = [
        spec.name
        for spec in specs
        if spec.effect_policy is ToolEffectPolicy.side_effect and spec.approval_required
    ]
    assert {"documents.delete", "documents.reindex", "evaluations.run"}.issubset(approval_required_tools)


def test_default_tool_specs_include_document_intelligence_read_tools() -> None:
    specs = build_default_tool_specs()
    tool_names = {spec.name for spec in specs}
    assert {
        "search_documents",
        "get_document_detail",
        "list_document_chunks",
        "answer_from_context",
        "summarize_document",
        "compare_documents",
    }.issubset(tool_names)
