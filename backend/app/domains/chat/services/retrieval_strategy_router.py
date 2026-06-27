"""Dynamic retrieval strategy router (F341).

Maps the answer planner's strategy classification to a concrete retrieval
method, taking into account feature-flag availability, admin overrides from
the RAG profile, and optional user-level request overrides.

Design constraints:
- Runs synchronously after the planner and before retrieval (~0 ms).
- Never makes an LLM call.
- On any failure returns RetrievalRouteResult with method="auto_fallback".
- The route result is stored in trust metadata for UI display and audit.
- Internal `reason` strings are NOT surfaced to end-users — only
  `method` and `method_label` appear in the trust panel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

logger = logging.getLogger("chat.retrieval_strategy_router")

RetrievalMethod = Literal[
    "vector",
    "keyword",
    "hybrid",
    "table_aware",
    "parent_child",
    "graph_rag",
    "connector_aware",
    "auto_fallback",
]

RETRIEVAL_METHOD_LABELS: dict[str, str] = {
    "vector": "Vector search",
    "keyword": "Keyword search",
    "hybrid": "Hybrid search",
    "table_aware": "Table-aware search",
    "parent_child": "Context-expanded search",
    "graph_rag": "Graph-assisted search",
    "connector_aware": "Connector-scoped search",
    "auto_fallback": "Standard search",
}

# Planner strategy → preferred retrieval method (when all features available).
# Priority order matches the planner: legal_compliance → policy_lookup → … → standard.
_STRATEGY_METHOD_MAP: dict[str, RetrievalMethod] = {
    "legal_compliance": "hybrid",  # exact legal language + semantic
    "policy_lookup": "keyword",  # exact policy IDs and names
    "comparison": "hybrid",  # wide recall for both sides
    "incident_decision_support": "hybrid",  # high-risk incident summaries + recall
    "table_heavy": "table_aware",  # table-boost vector retrieval
    "graph_assisted": "graph_rag",  # GraphRAG entity traversal
    "connector_search": "connector_aware",  # connector-scoped
    "troubleshooting": "hybrid",  # exact error codes + semantic context
    "summary": "parent_child",  # broader parent-section context
    "standard": "hybrid",  # default when hybrid is available
}

_VALID_OVERRIDE_VALUES: frozenset[str] = frozenset(RETRIEVAL_METHOD_LABELS.keys())

# Methods that require hybrid retrieval to be enabled.
_HYBRID_DEPENDENT: frozenset[RetrievalMethod] = frozenset({"hybrid", "table_aware"})

# Methods that require GraphRAG to be enabled.
_GRAPH_DEPENDENT: frozenset[RetrievalMethod] = frozenset({"graph_rag"})


@dataclass(frozen=True)
class FeatureAvailability:
    """Snapshot of which retrieval features are enabled for this request."""

    hybrid_retrieval_enabled: bool = False
    graph_rag_enabled: bool = False
    parent_context_expansion_enabled: bool = False
    keyword_retrieval_enabled: bool = False


@dataclass(frozen=True)
class RetrievalRouteResult:
    """Output of the retrieval strategy router.

    Callers should:
    - Apply `method` to influence which retrieval branches execute.
    - Store this record in trust metadata.
    - Use `method_label` for safe activity-timeline / UI display.
    - Never surface `reason` to end-users — it may contain internal signals.
    """

    method: str  # one of RetrievalMethod values
    method_label: str
    reason: str  # internal only — not exposed to UI
    override_applied: bool = False
    override_source: Literal["user", "rag_profile", None] = None
    routing_latency_ms: int = 0


class RetrievalStrategyRouter:
    """Routes a question to the best retrieval method based on planner output.

    Resolution order (first match wins):
      1. User-level request override (when allowed by feature flag).
      2. RAG-profile admin override.
      3. Auto-route from planner strategy, constrained by feature availability.
      4. Fallback to "vector" (always available).
    """

    def route(
        self,
        *,
        planner_strategy: str,
        features: FeatureAvailability,
        profile_override: str | None = None,
        request_override: str | None = None,
        allow_user_override: bool = False,
    ) -> RetrievalRouteResult:
        """Determine the retrieval method for this request.

        Args:
            planner_strategy: The strategy returned by AnswerPlannerService.
            features: Which retrieval sub-systems are currently enabled.
            profile_override: Admin-set override from RagProfileConfig
                (``retrieval_strategy_override`` field).
            request_override: Per-request override from the API caller
                (only honoured when ``allow_user_override`` is True).
            allow_user_override: True when the feature flag
                ``feature_enable_retrieval_strategy_user_override`` is on.
        """
        started = perf_counter()
        try:
            method, reason, override_applied, override_source = self._resolve(
                planner_strategy=planner_strategy,
                features=features,
                profile_override=profile_override,
                request_override=request_override,
                allow_user_override=allow_user_override,
            )
            constrained, reason = self._apply_feature_constraints(
                method=method, features=features, reason=reason
            )
            latency_ms = int((perf_counter() - started) * 1000)
            label = RETRIEVAL_METHOD_LABELS.get(constrained, "Standard search")
            logger.debug(
                "retrieval_strategy_router method=%s override=%s latency_ms=%d",
                constrained,
                override_source,
                latency_ms,
            )
            return RetrievalRouteResult(
                method=constrained,
                method_label=label,
                reason=reason,
                override_applied=override_applied,
                override_source=override_source,
                routing_latency_ms=latency_ms,
            )
        except Exception as exc:
            logger.warning("retrieval_strategy_router failed, using fallback: %s", exc)
            return RetrievalRouteResult(
                method="auto_fallback",
                method_label="Standard search",
                reason="router_error",
                routing_latency_ms=0,
            )

    @staticmethod
    def _resolve(
        *,
        planner_strategy: str,
        features: FeatureAvailability,
        profile_override: str | None,
        request_override: str | None,
        allow_user_override: bool,
    ) -> tuple[RetrievalMethod, str, bool, Literal["user", "rag_profile", None]]:
        # 1 — user override (only when feature flag permits it)
        if allow_user_override and request_override:
            cleaned = request_override.strip().lower()
            if cleaned in _VALID_OVERRIDE_VALUES:
                return cleaned, "user_override", True, "user"  # type: ignore[return-value]

        # 2 — admin / RAG-profile override
        if profile_override:
            cleaned = profile_override.strip().lower()
            if cleaned in _VALID_OVERRIDE_VALUES and cleaned != "auto":
                return cleaned, "profile_override", True, "rag_profile"  # type: ignore[return-value]

        # 3 — auto-route from planner strategy
        method = _STRATEGY_METHOD_MAP.get(planner_strategy, "hybrid")
        # Fall through to feature-constraint check in caller.
        return method, f"auto:{planner_strategy}", False, None  # type: ignore[return-value]

    @staticmethod
    def _apply_feature_constraints(
        *,
        method: RetrievalMethod,
        features: FeatureAvailability,
        reason: str,
    ) -> tuple[RetrievalMethod, str]:
        """Downgrade the method if its required feature is unavailable."""
        if method in _HYBRID_DEPENDENT and not features.hybrid_retrieval_enabled:
            return "vector", f"{reason}:hybrid_unavailable"
        if method in _GRAPH_DEPENDENT and not features.graph_rag_enabled:
            return "hybrid" if features.hybrid_retrieval_enabled else "vector", (
                f"{reason}:graph_unavailable"
            )
        if method == "parent_child" and not features.parent_context_expansion_enabled:
            return "vector", f"{reason}:parent_expansion_unavailable"
        if method == "keyword" and not features.keyword_retrieval_enabled:
            return "vector", f"{reason}:keyword_unavailable"
        if method == "connector_aware" and not features.hybrid_retrieval_enabled:
            return "vector", f"{reason}:connector_hybrid_unavailable"
        return method, reason
