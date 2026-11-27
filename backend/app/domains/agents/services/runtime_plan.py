"""Deterministic tool plan, argument resolution, and observation (split from ``runtime.py``).

The plan is a pure function of the validated request, so a worker that resumes a run builds
the same plan the first task stored in the planning step (R06-13).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.config import settings
from app.domains.agents.schemas import (
    AgentRuntimeMode,
    AgentRuntimeRequest,
    PlannedToolSelection,
)
from app.domains.agents.services.runtime_context import _RuntimeContext, select_mode
from app.domains.agents.services.safety_guardrails import PromptInjectionGuard

_SELECTED_DOCUMENT_IDS = "__selected_document_ids__"
_SELECTED_DOCUMENT_ID = "__selected_document_id__"


def build_plan(*, request: AgentRuntimeRequest) -> list[PlannedToolSelection]:
    mode = select_mode(request)
    question = request.question or request.objective
    top_k = request.top_k or settings.retrieval_final_top_k
    rerank = request.rerank if request.rerank is not None else True

    selections: list[PlannedToolSelection] = []
    if not request.document_ids:
        selections.append(
            PlannedToolSelection(
                step_name="discover_documents",
                tool_name="search_documents",
                arguments={
                    "query": request.document_query or None,
                    "status": "indexed",
                    "sort_by": "updated_at",
                    "sort_order": "desc",
                    "limit": 25,
                    "offset": 0,
                },
                rationale="Find indexed accessible documents to ground the answer.",
            )
        )

    if mode is AgentRuntimeMode.answer:
        selections.append(
            PlannedToolSelection(
                step_name="grounded_answer",
                tool_name="answer_from_context",
                arguments={
                    "question": question,
                    "document_ids": _SELECTED_DOCUMENT_IDS,
                    "top_k": top_k,
                    "rerank": rerank,
                },
                rationale="Answer using retrieved document context with citations and confidence.",
            )
        )
    elif mode is AgentRuntimeMode.summarize:
        selections.append(
            PlannedToolSelection(
                step_name="document_summary",
                tool_name="summarize_document",
                arguments={
                    "document_id": _SELECTED_DOCUMENT_ID,
                    "top_k": top_k,
                    "rerank": rerank,
                },
                rationale="Create a grounded summary for one selected document.",
            )
        )
    else:
        selections.append(
            PlannedToolSelection(
                step_name="document_comparison",
                tool_name="compare_documents",
                arguments={
                    "question": question,
                    "document_ids": _SELECTED_DOCUMENT_IDS,
                    "top_k": top_k,
                    "rerank": rerank,
                },
                rationale="Compare grounded evidence across selected documents.",
            )
        )

    return selections


def parse_document_ids(document_ids: list[str]) -> list[UUID]:
    parsed: list[UUID] = []
    seen: set[str] = set()
    for raw_document_id in document_ids:
        normalized = raw_document_id.strip()
        if not normalized or normalized in seen:
            continue
        try:
            document_id = UUID(normalized)
        except ValueError:
            continue
        seen.add(normalized)
        parsed.append(document_id)
    return parsed


def resolve_selection_arguments(
    *,
    selection: PlannedToolSelection,
    context: _RuntimeContext,
) -> dict[str, Any]:
    arguments = dict(selection.arguments)
    if arguments.get("document_ids") == _SELECTED_DOCUMENT_IDS:
        if not context.selected_document_ids:
            raise ValueError("No accessible indexed documents were found for this request")
        if selection.tool_name == "compare_documents" and len(context.selected_document_ids) < 2:
            raise ValueError("At least two documents are required for compare mode")
        arguments["document_ids"] = context.selected_document_ids
    if arguments.get("document_id") == _SELECTED_DOCUMENT_ID:
        if not context.selected_document_ids:
            raise ValueError("No accessible indexed documents were found for this request")
        arguments["document_id"] = context.selected_document_ids[0]
    return arguments


def observe_after_step(
    *,
    selection: PlannedToolSelection,
    output: dict[str, Any],
    context: _RuntimeContext,
    safety_guard: PromptInjectionGuard,
) -> None:
    if selection.tool_name != "search_documents":
        return
    items = output.get("items")
    if not isinstance(items, list):
        return
    document_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if settings.agent_document_instruction_guard_enabled:
            for value in item.values():
                if isinstance(value, str) and safety_guard.is_instruction_like(value):
                    context.blocked_document_instruction_signals += 1
                    break
        document_id = item.get("document_id")
        status = item.get("status")
        if (
            isinstance(document_id, str)
            and status == "indexed"
            and is_uuid_string(document_id.strip())
        ):
            document_ids.append(document_id)
    # Keep selection bounded for downstream cost/runtime.
    context.selected_document_ids = document_ids[:10]


def is_uuid_string(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
