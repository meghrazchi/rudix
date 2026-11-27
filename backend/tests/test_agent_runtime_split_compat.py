"""``runtime.py`` split (R06-13): names, module sizes, and MCP exposure stay as they were."""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path

import pytest

from app.domains.agents.schemas import (
    AgentBudgetConfig,
    AgentRuntimeMode,
    AgentRuntimeRequest,
    PlannedToolSelection,
)
from app.domains.agents.services import runtime as runtime_module
from app.domains.agents.services.runtime import AgentRuntime, _RuntimeContext
from app.domains.agents.services.runtime_context import (
    check_budget_after_step,
    check_budget_before_step,
)
from app.domains.agents.services.runtime_steps import side_effect_idempotency_key
from app.domains.agents.services.tool_registry import build_default_tool_specs

SERVICES_DIR = Path(runtime_module.__file__).resolve().parent

# Names other modules and tests reach on the runtime (instance or class).
RUNTIME_NAMES = (
    "execute",
    "preview_plan",
    "_executor",
    "_source_scope_service",
    "_registry",
    "_repository",
    "_check_budget_before_step",
    "_check_budget_after_step",
    "_record_runtime_usage_event",
    "_resolve_budget",
    "_select_mode",
    "_build_plan",
    "_build_outcome",
    "_fail_run",
    "_cancel_run",
    "_is_cancelled_run",
    "_resolve_selection_arguments",
    "_observe_after_step",
    "_extract_usage",
    "_audit_started",
    "_audit_completed",
    "_audit_failed",
    "_organization_uuid",
    "_user_uuid",
)

# The MCP surface before the worker change (R06-13 must not change it).
MCP_PUBLIC_TOOLS = [
    ("answer_from_context", "read_only"),
    ("ask_documents", "read_only"),
    ("compare", "read_only"),
    ("compare_documents", "read_only"),
    ("get_document_chunks", "read_only"),
    ("get_document_detail", "read_only"),
    ("list_document_chunks", "read_only"),
    ("search_documents", "read_only"),
    ("summarize", "read_only"),
    ("summarize_document", "read_only"),
]
DEFAULT_TOOL_SURFACES = [
    ("answer_from_context", ("api", "mcp"), "read_only"),
    ("chat.answer", ("api",), "side_effect"),
    ("compare_documents", ("api", "mcp"), "read_only"),
    ("documents.chunks.list", ("api", "mcp"), "read_only"),
    ("documents.delete", ("api",), "side_effect"),
    ("documents.get", ("api", "mcp"), "read_only"),
    ("documents.list", ("api", "mcp"), "read_only"),
    ("documents.reindex", ("api",), "side_effect"),
    ("evaluations.run", ("api",), "side_effect"),
    ("get_document_detail", ("api", "mcp"), "read_only"),
    ("list_document_chunks", ("api", "mcp"), "read_only"),
    ("pipeline.runs.get", ("api", "mcp"), "read_only"),
    ("search_documents", ("api", "mcp"), "read_only"),
    ("summarize_document", ("api", "mcp"), "read_only"),
]


def test_runtime_names_stay_reachable() -> None:
    runtime = AgentRuntime()
    for name in RUNTIME_NAMES:
        assert hasattr(runtime, name), name
        if not name.startswith("_") or callable(getattr(AgentRuntime, name, None)):
            assert hasattr(AgentRuntime, name), name


def test_budget_check_keeps_its_signature_and_source() -> None:
    signature = inspect.signature(AgentRuntime._check_budget_before_step)
    assert set(signature.parameters) == {"budget", "context", "elapsed_ms"}
    assert "resolved_profile" not in inspect.getsource(AgentRuntime._check_budget_before_step)
    assert AgentRuntime._check_budget_before_step is check_budget_before_step
    assert AgentRuntime._check_budget_after_step is check_budget_after_step


def test_budget_rules_are_unchanged() -> None:
    budget = AgentBudgetConfig(
        max_steps=2, max_runtime_ms=1000, max_tool_calls=3, max_total_tokens=10
    )
    context = _RuntimeContext(mode=AgentRuntimeMode.answer, question="q", selected_document_ids=[])
    assert check_budget_before_step(budget=budget, context=context, elapsed_ms=0) is None
    assert (
        check_budget_before_step(budget=budget, context=context, elapsed_ms=1001)
        == "Runtime budget exceeded"
    )
    context.tool_calls_executed = 3
    assert (
        check_budget_before_step(budget=budget, context=context, elapsed_ms=0)
        == "Tool-call budget exceeded"
    )
    context.steps_executed = 2
    assert (
        check_budget_before_step(budget=budget, context=context, elapsed_ms=0)
        == "Step budget exceeded"
    )
    context.total_tokens = 11
    assert check_budget_after_step(budget=budget, context=context) == "Token budget exceeded"
    cost_budget = AgentBudgetConfig(max_total_cost_usd=Decimal("0.5"))
    context.total_tokens = 0
    context.total_cost_usd = Decimal("0.6")
    assert check_budget_after_step(budget=cost_budget, context=context) == "Cost budget exceeded"


def test_plan_and_mode_are_unchanged() -> None:
    runtime = AgentRuntime()
    plan = runtime.preview_plan(request=AgentRuntimeRequest(objective="Summarize the handbook"))
    assert [item.tool_name for item in plan] == ["search_documents", "summarize_document"]
    compare = AgentRuntimeRequest(objective="Compare", document_ids=["a", "b"])
    assert runtime._select_mode(compare) is AgentRuntimeMode.compare
    assert [item.tool_name for item in runtime._build_plan(request=compare)] == [
        "compare_documents"
    ]


def test_selection_arguments_and_outcome() -> None:
    runtime = AgentRuntime()
    context = _RuntimeContext(
        mode=AgentRuntimeMode.summarize, question="q", selected_document_ids=[]
    )
    selection = PlannedToolSelection(
        step_name="document_summary",
        tool_name="summarize_document",
        arguments={"document_id": "__selected_document_id__"},
    )
    with pytest.raises(ValueError):
        runtime._resolve_selection_arguments(selection=selection, context=context)
    context.selected_document_ids = ["d1"]
    resolved = runtime._resolve_selection_arguments(selection=selection, context=context)
    assert resolved == {"document_id": "d1"}
    context.latest_output = {"summary": "S", "citations": [{"chunk_id": "c"}], "not_found": True}
    outcome = runtime._build_outcome(context=context)
    assert outcome.answer == "S" and outcome.not_found and outcome.citations
    context.mode = AgentRuntimeMode.compare
    context.latest_output = {"comparison": "C", "citations": "bad", "confidence": "bad"}
    outcome = runtime._build_outcome(context=context)
    assert outcome.answer == "C" and outcome.citations == [] and outcome.confidence == {}


def test_side_effect_idempotency_key_format() -> None:
    from uuid import UUID

    run_id = UUID("11111111-1111-1111-1111-111111111111")
    assert side_effect_idempotency_key(run_id, 2, "documents.reindex") == (
        "11111111-1111-1111-1111-111111111111:2:documents.reindex"
    )


def test_runtime_modules_stay_under_500_lines() -> None:
    for path in sorted(SERVICES_DIR.glob("runtime*.py")):
        lines = path.read_text(encoding="utf-8").count("\n")
        assert lines < 500, f"{path.name} has {lines} lines"


def test_mcp_tool_list_is_unchanged() -> None:
    from app.mcp.server import MCPToolRuntime

    public = [
        (spec.name, spec.effect_policy.value) for spec in MCPToolRuntime().list_public_specs()
    ]
    assert public == MCP_PUBLIC_TOOLS
    surfaces = sorted(
        (spec.name, tuple(item.value for item in spec.surfaces), spec.effect_policy.value)
        for spec in build_default_tool_specs()
    )
    assert surfaces == DEFAULT_TOOL_SURFACES
    for name, tool_surfaces, effect in surfaces:
        if effect == "side_effect":
            assert "mcp" not in tool_surfaces, name
