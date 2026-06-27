"""Answer strategy planner (F339).

Classifies the incoming question into an answer strategy and decides whether
the question is high-risk (requiring critic + refiner passes before display).

Design constraints:
- Runs before retrieval so it must be fast — keyword heuristics only.
- On any failure returns strategy="standard", high_risk=False so the caller
  can proceed safely without the planner.
- The planner NEVER sees retrieved chunk text — it operates on the question
  text only.
- High-risk strategies are configurable per RAG profile so organisations can
  choose which answer types warrant the extra critic+refiner pass.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

logger = logging.getLogger("chat.answer_planner")

PlannerStrategy = Literal[
    "policy_lookup",
    "comparison",
    "legal_compliance",
    "table_heavy",
    "graph_assisted",
    "connector_search",
    "standard",
]

STRATEGY_LABELS: dict[str, str] = {
    "policy_lookup": "Policy lookup",
    "comparison": "Comparison",
    "legal_compliance": "Legal / compliance",
    "table_heavy": "Table-heavy",
    "graph_assisted": "Graph-assisted",
    "connector_search": "Connector search",
    "standard": "Standard",
}

_DEFAULT_HIGH_RISK_STRATEGIES: frozenset[str] = frozenset(
    {"legal_compliance", "policy_lookup", "comparison"}
)

# ---------------------------------------------------------------------------
# Keyword patterns (compiled once at import time)
# ---------------------------------------------------------------------------

_LEGAL_COMPLIANCE_RE = re.compile(
    r"\b(legal|law|lawsuit|regulation|regulatory|compliance|gdpr|hipaa|soc2?|pci|iso[ _]?27001|"
    r"contract|contractual|liability|indemnif|arbitration|jurisdiction|statutory|legislation|"
    r"breach|penalty|sanction|due diligence|audit trail|data protection|privacy policy|"
    r"nda|non-disclosure|intellectual property|patent|trademark|copyright|tort)\b",
    re.IGNORECASE,
)

_POLICY_LOOKUP_RE = re.compile(
    r"\b(policy|policies|rule|rules|procedure|guideline|protocol|standard|handbook|"
    r"allowed|forbidden|prohibited|permitted|must|required|mandate|obligation|"
    r"terms of (service|use)|acceptable use|code of conduct|hr policy|leave policy|"
    r"expense policy|travel policy|security policy|data policy|retention policy)\b",
    re.IGNORECASE,
)

_COMPARISON_RE = re.compile(
    r"\b(compar(e|ing|ison)|difference(s)? between|vs\.?|versus|"
    r"better|worse|prefer|advantage|disadvantage|pros? and cons?|"
    r"which (is|one|option|approach)|side[- ]by[- ]side|contrast|distinguish|"
    r"trade[- ]off|alternative)\b",
    re.IGNORECASE,
)

_TABLE_HEAVY_RE = re.compile(
    r"\b(list all|enumerate|breakdown|how many|count all|total number|"
    r"sum (of|up)|average|percentage|ratio|table of|in a table|spreadsheet|"
    r"row by row|column|chart|figure \d+)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannerResult:
    """Output of the answer planner.

    Callers should:
    - Use strategy to annotate trust metadata and activity step detail.
    - Use high_risk to decide whether critic + refiner passes are required.
    - Never block on planner failure — the fallback is strategy=standard, high_risk=False.
    """

    strategy: str  # one of PlannerStrategy values
    high_risk: bool
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AnswerPlannerService:
    """Keyword-based answer strategy classifier.

    Classifies the incoming question into one of seven strategies and flags
    questions as high-risk (legal, compliance, policy, comparison) so the
    critic + refiner pipeline is activated for those answers.

    All classification is heuristic (regex-based) so it adds <1 ms of latency
    before retrieval and never makes an LLM call.
    """

    def __init__(
        self,
        *,
        high_risk_strategies: frozenset[str] | None = None,
    ) -> None:
        self._default_high_risk = (
            _DEFAULT_HIGH_RISK_STRATEGIES
            if high_risk_strategies is None
            else high_risk_strategies
        )

    @staticmethod
    def _fallback() -> PlannerResult:
        return PlannerResult(strategy="standard", high_risk=False, latency_ms=0)

    def classify(
        self,
        *,
        question: str,
        table_query_detected: bool = False,
        graph_context_available: bool = False,
        connector_search_scope: bool = False,
        high_risk_strategies_override: frozenset[str] | None = None,
    ) -> PlannerResult:
        """Classify the question and return a strategy + high_risk flag.

        Args:
            question: The raw user question text.
            table_query_detected: True when the table retrieval service already
                detected a table-centric question (reuses existing pipeline signal).
            graph_context_available: True when GraphRAG is enabled for the org.
            connector_search_scope: True when the query is scoped to connector sources.
            high_risk_strategies_override: Per-call override from RAG profile config.
        """
        started = perf_counter()
        try:
            effective_high_risk = (
                self._default_high_risk
                if high_risk_strategies_override is None
                else high_risk_strategies_override
            )
            strategy = self._detect_strategy(
                question=question,
                table_query_detected=table_query_detected,
                graph_context_available=graph_context_available,
                connector_search_scope=connector_search_scope,
            )
            high_risk = strategy in effective_high_risk
            latency_ms = int((perf_counter() - started) * 1000)
            logger.debug(
                "answer_planner strategy=%s high_risk=%s latency_ms=%d",
                strategy,
                high_risk,
                latency_ms,
            )
            return PlannerResult(strategy=strategy, high_risk=high_risk, latency_ms=latency_ms)
        except Exception as exc:
            logger.warning("answer_planner failed, using fallback: %s", exc)
            return self._fallback()

    @staticmethod
    def _detect_strategy(
        *,
        question: str,
        table_query_detected: bool,
        graph_context_available: bool,
        connector_search_scope: bool,
    ) -> str:
        # Priority order (highest to lowest): legal_compliance > policy_lookup >
        # comparison > table_heavy > graph_assisted > connector_search > standard
        if _LEGAL_COMPLIANCE_RE.search(question):
            return "legal_compliance"
        if _POLICY_LOOKUP_RE.search(question):
            return "policy_lookup"
        if _COMPARISON_RE.search(question):
            return "comparison"
        if table_query_detected or _TABLE_HEAVY_RE.search(question):
            return "table_heavy"
        if graph_context_available:
            return "graph_assisted"
        if connector_search_scope:
            return "connector_search"
        return "standard"
