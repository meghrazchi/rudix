"""Workflow planner for plan-before-execute agentic tasks (F344)."""

from __future__ import annotations

from typing import Any, Literal

from app.domains.agents.schemas import (
    AgentPlanPreviewResponse,
    AgentRuntimeMode,
    AgentRuntimeRequest,
)
from app.domains.agents.schemas.agent_tools import ToolEffectPolicy
from app.domains.agents.services.runtime import AgentRuntime
from app.domains.agents.services.tool_registry import ToolRegistry, build_default_tool_specs
from app.domains.chat.services.answer_planner_service import AnswerPlannerService

WorkflowType = Literal[
    "audit_evidence_pack",
    "policy_comparison",
    "contract_obligation_analysis",
    "onboarding_faq_preparation",
    "connector_content_summarization",
    "low_confidence_answer_investigation",
]

WorkflowAction = Literal[
    "export",
    "share",
    "connector_sync",
    "public_link",
    "permission_change",
]

_WORKFLOW_DEFAULTS: dict[str, dict[str, Any]] = {
    "audit_evidence_pack": {
        "mode": AgentRuntimeMode.compare,
        "objective": "Build an audit evidence pack from the selected sources with citations.",
        "rerank": True,
    },
    "policy_comparison": {
        "mode": AgentRuntimeMode.compare,
        "objective": "Compare the relevant policies and surface the material differences with citations.",
        "rerank": True,
    },
    "contract_obligation_analysis": {
        "mode": AgentRuntimeMode.compare,
        "objective": "Analyse contract obligations across the available agreements and cite the source clauses.",
        "rerank": True,
    },
    "onboarding_faq_preparation": {
        "mode": AgentRuntimeMode.summarize,
        "objective": "Prepare an onboarding FAQ from the selected onboarding sources with grounded citations.",
        "rerank": False,
    },
    "connector_content_summarization": {
        "mode": AgentRuntimeMode.summarize,
        "objective": "Summarise the selected connector content into a reusable workflow output with citations.",
        "rerank": True,
    },
    "low_confidence_answer_investigation": {
        "mode": AgentRuntimeMode.answer,
        "objective": "Investigate the low-confidence answer, verify the evidence, and explain the trust gaps.",
        "rerank": True,
    },
}


def _workflow_title(workflow_type: WorkflowType) -> str:
    return {
        "audit_evidence_pack": "Audit evidence pack",
        "policy_comparison": "Policy comparison",
        "contract_obligation_analysis": "Contract obligation analysis",
        "onboarding_faq_preparation": "Onboarding FAQ preparation",
        "connector_content_summarization": "Connector content summarization",
        "low_confidence_answer_investigation": "Low-confidence answer investigation",
    }[workflow_type]


class WorkflowPlannerService:
    def __init__(
        self,
        *,
        runtime: AgentRuntime | None = None,
        registry: ToolRegistry | None = None,
        answer_planner: AnswerPlannerService | None = None,
    ) -> None:
        self._runtime = runtime or AgentRuntime()
        self._registry = registry or ToolRegistry(specs=build_default_tool_specs())
        self._answer_planner = answer_planner or AnswerPlannerService()

    def preview(
        self,
        *,
        workflow_type: WorkflowType,
        request: AgentRuntimeRequest | None = None,
        requested_actions: list[WorkflowAction] | None = None,
    ) -> AgentPlanPreviewResponse:
        defaults = _WORKFLOW_DEFAULTS[workflow_type]
        workflow_request = request or AgentRuntimeRequest(
            objective=str(defaults["objective"]),
            mode=defaults["mode"],
            rerank=bool(defaults["rerank"]),
        )
        if not workflow_request.objective.strip():
            workflow_request = AgentRuntimeRequest(
                objective=str(defaults["objective"]),
                mode=workflow_request.mode,
                question=workflow_request.question,
                document_query=workflow_request.document_query,
                document_ids=workflow_request.document_ids,
                top_k=workflow_request.top_k,
                rerank=workflow_request.rerank,
                approval_ids=workflow_request.approval_ids,
                budget=workflow_request.budget,
                metadata=workflow_request.metadata,
            )

        plan = self._runtime.preview_plan(request=workflow_request)
        planner_result = self._answer_planner.classify(
            question=workflow_request.question or workflow_request.objective,
        )
        approvals_required = bool(requested_actions)
        for selection in plan:
            spec = self._registry.get_spec(selection.tool_name)
            if spec is not None and (
                spec.effect_policy is ToolEffectPolicy.side_effect or spec.approval_required
            ):
                approvals_required = True

        return AgentPlanPreviewResponse(
            objective=workflow_request.objective,
            mode=workflow_request.mode,
            plan=plan,
            workflow_type=workflow_type,
            planner_strategy=planner_result.strategy,
            planner_high_risk=planner_result.high_risk,
            requires_approval=approvals_required,
            requested_actions=list(requested_actions or []),
            request=workflow_request,
        )


def workflow_title(workflow_type: WorkflowType) -> str:
    return _workflow_title(workflow_type)
