"""Runtime state and budget rules of the agent loop (split from ``runtime.py``, R06-13).

``_RuntimeContext`` is the mutable state of one run: the selected documents, the latest
tool output, and the counters the budgets are checked against. The budget helpers are pure
functions so the inline and worker paths enforce exactly the same limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.domains.agents.schemas import (
    AgentBudgetConfig,
    AgentRuntimeMode,
    AgentRuntimeRequest,
)


@dataclass
class _RuntimeContext:
    mode: AgentRuntimeMode
    question: str
    selected_document_ids: list[str]
    latest_output: dict[str, Any] | None = None
    steps_executed: int = 0
    tool_calls_executed: int = 0
    total_tokens: int = 0
    total_cost_usd: Decimal = Decimal("0")
    blocked_document_instruction_signals: int = 0


def resolve_budget(requested_budget: AgentBudgetConfig | None) -> AgentBudgetConfig:
    defaults = AgentBudgetConfig(
        max_steps=settings.agent_max_steps,
        max_runtime_ms=max(settings.agent_max_steps * settings.agent_tool_timeout_ms, 5_000),
        max_tool_calls=settings.agent_tool_max_calls_per_run,
        max_total_tokens=None,
        max_total_cost_usd=None,
    )
    if requested_budget is None:
        return defaults
    return AgentBudgetConfig(
        max_steps=min(requested_budget.max_steps, defaults.max_steps),
        max_runtime_ms=min(requested_budget.max_runtime_ms, defaults.max_runtime_ms),
        max_tool_calls=min(requested_budget.max_tool_calls, defaults.max_tool_calls),
        max_total_tokens=requested_budget.max_total_tokens,
        max_total_cost_usd=requested_budget.max_total_cost_usd,
    )


def budget_payload(budget: AgentBudgetConfig) -> dict[str, Any]:
    """The ``agent_runs.budget`` column value of a resolved budget."""
    return {
        "max_steps": budget.max_steps,
        "max_runtime_ms": budget.max_runtime_ms,
        "max_tool_calls": budget.max_tool_calls,
        "max_total_tokens": budget.max_total_tokens,
        "max_total_cost_usd": str(budget.max_total_cost_usd)
        if budget.max_total_cost_usd is not None
        else None,
    }


def select_mode(request: AgentRuntimeRequest) -> AgentRuntimeMode:
    if request.mode is not AgentRuntimeMode.auto:
        return request.mode
    objective = request.objective.lower()
    if len(request.document_ids) > 1 or "compare" in objective:
        return AgentRuntimeMode.compare
    if "summary" in objective or "summarize" in objective:
        return AgentRuntimeMode.summarize
    return AgentRuntimeMode.answer


def check_budget_before_step(
    *,
    budget: AgentBudgetConfig,
    context: _RuntimeContext,
    elapsed_ms: int,
) -> str | None:
    if context.steps_executed >= budget.max_steps:
        return "Step budget exceeded"
    if context.tool_calls_executed >= budget.max_tool_calls:
        return "Tool-call budget exceeded"
    if elapsed_ms > budget.max_runtime_ms:
        return "Runtime budget exceeded"
    return None


def check_budget_after_step(*, budget: AgentBudgetConfig, context: _RuntimeContext) -> str | None:
    if budget.max_total_tokens is not None and context.total_tokens > budget.max_total_tokens:
        return "Token budget exceeded"
    if budget.max_total_cost_usd is not None and context.total_cost_usd > budget.max_total_cost_usd:
        return "Cost budget exceeded"
    return None


def extract_usage(output: dict[str, Any]) -> dict[str, Any]:
    debug = output.get("debug")
    if not isinstance(debug, dict):
        return {"total_tokens": 0, "total_cost_usd": Decimal("0")}
    usage = debug.get("usage")
    if not isinstance(usage, dict):
        return {"total_tokens": 0, "total_cost_usd": Decimal("0")}
    raw_tokens = usage.get("total_tokens", 0)
    raw_cost = usage.get("total_cost_usd", "0")
    try:
        total_tokens = int(raw_tokens)
    except (TypeError, ValueError):
        total_tokens = 0
    try:
        total_cost_usd = Decimal(str(raw_cost))
    except Exception:
        total_cost_usd = Decimal("0")
    return {
        "total_tokens": max(total_tokens, 0),
        "total_cost_usd": max(total_cost_usd, Decimal("0")),
    }


def safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
