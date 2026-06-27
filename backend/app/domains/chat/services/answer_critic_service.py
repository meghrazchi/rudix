"""Answer critic (F339).

Aggregates quality signals already computed by the RAG pipeline into a
structured list of warnings and a severity rating. The critic decides whether
the refiner is needed for this answer.

Design constraints:
- The critic is SYNCHRONOUS and makes NO LLM calls — it aggregates signals
  that have already been computed (freshness, OCR quality, conflict detection,
  grounded verifier). It is therefore safe to run on every high-risk answer
  with negligible latency overhead.
- Raw chunk text is NEVER passed into or stored by the critic.
- On any error the critic returns a CriticResult with no warnings so the caller
  can proceed without triggering the refiner.
- The refiner_severity_threshold controls the minimum severity that activates
  the refiner. Default is "medium" so only medium/high-severity issues prompt
  a rewrite pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal

logger = logging.getLogger("chat.answer_critic")

CriticSeverity = Literal["none", "low", "medium", "high"]

_SEVERITY_INT: dict[str, int] = {"none": 0, "low": 1, "medium": 2, "high": 3}
_INT_SEVERITY: dict[int, CriticSeverity] = {0: "none", 1: "low", 2: "medium", 3: "high"}

# Minimum severity level contributed by each warning code (1=low, 2=medium, 3=high)
_CODE_SEVERITY: dict[str, int] = {
    "citation_unsupported": 3,  # high — missing citation support is a serious issue
    "source_conflict": 3,  # high — conflicting sources undermine answer trust
    "no_sources_found": 3,  # high — no evidence at all
    "missing_evidence": 2,  # medium — insufficient evidence for some claims
    "stale_source": 1,  # low — staleness is a warning, not a blocker
    "ocr_low_quality": 1,  # low — OCR issues reduce but don't eliminate trust
    "table_low_confidence": 1,  # low — table extraction issues
    "extraction_quality": 1,  # low — document extraction issues
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CriticWarning:
    """A single warning produced by the critic."""

    code: str
    detail: str
    severity_level: int  # 1=low, 2=medium, 3=high


@dataclass
class CriticResult:
    """Aggregated critic output.

    Callers should:
    - Read warnings to populate trust metadata.
    - Use requires_refiner to decide whether to run the AnswerRefinerService.
    - Pass refiner_instruction to the refiner's LLM prompt.
    """

    warnings: list[CriticWarning] = field(default_factory=list)
    severity: CriticSeverity = "none"
    requires_refiner: bool = False
    refiner_instruction: str = ""
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AnswerCriticService:
    """Synchronous answer quality critic.

    Aggregates evidence quality signals from the pipeline state into a list of
    structured warnings and decides whether the refiner needs to rewrite the
    answer.

    Args:
        refiner_severity_threshold: Minimum critic severity that activates the
            refiner. "medium" means both medium and high severity trigger a
            rewrite pass; "high" means only high-severity issues do.
    """

    def __init__(
        self,
        *,
        refiner_severity_threshold: CriticSeverity = "medium",
    ) -> None:
        self._refiner_min_level: int = _SEVERITY_INT[refiner_severity_threshold]

    @staticmethod
    def _fallback() -> CriticResult:
        return CriticResult()

    def evaluate(
        self,
        *,
        not_found: bool,
        selected_chunk_count: int,
        citation_count: int,
        # Grounded verifier signals (may be absent if verifier not run)
        gv_applied: bool = False,
        gv_unsupported_count: int = 0,
        gv_conflicting_count: int = 0,
        gv_not_enough_evidence_count: int = 0,
        # Conflict detection signals
        conflict_detected: bool = False,
        # Source freshness signals
        freshness_stale_count: int = 0,
        freshness_excluded_count: int = 0,
        freshness_all_excluded_fallback: bool = False,
        # OCR quality signals
        ocr_low_confidence_chunk_count: int = 0,
        # Evidence quality signals (F315)
        table_low_confidence_count: int = 0,
        extraction_warning_count: int = 0,
    ) -> CriticResult:
        """Evaluate answer quality and return structured warnings.

        All inputs are integers or booleans derived from pipeline state — no
        text, no chunk data. This ensures no source-text leakage through the
        critic path.

        Returns:
            CriticResult with warnings, overall severity, requires_refiner flag,
            and a plain-English refiner_instruction for the refiner's LLM prompt.
        """
        started = perf_counter()
        try:
            warnings: list[CriticWarning] = []

            # No evidence at all — most severe critic finding
            if not_found or selected_chunk_count == 0:
                warnings.append(
                    CriticWarning(
                        code="no_sources_found",
                        detail="No relevant source documents were retrieved.",
                        severity_level=3,
                    )
                )

            # Grounded verifier — unsupported claims
            if gv_applied and gv_unsupported_count > 0:
                warnings.append(
                    CriticWarning(
                        code="citation_unsupported",
                        detail=(f"{gv_unsupported_count} claim(s) lacked direct source support."),
                        severity_level=3,
                    )
                )

            # Conflicting sources — from either conflict detection or verifier
            if conflict_detected or (gv_applied and gv_conflicting_count > 0):
                count = gv_conflicting_count if (gv_applied and gv_conflicting_count > 0) else 0
                warnings.append(
                    CriticWarning(
                        code="source_conflict",
                        detail=(
                            f"Sources conflict on {count} claim(s)."
                            if count
                            else "Retrieved sources contain conflicting information."
                        ),
                        severity_level=3,
                    )
                )

            # Insufficient evidence — claims where sources are present but not conclusive
            if gv_applied and gv_not_enough_evidence_count > 0:
                warnings.append(
                    CriticWarning(
                        code="missing_evidence",
                        detail=(
                            f"{gv_not_enough_evidence_count} claim(s) had insufficient evidence."
                        ),
                        severity_level=2,
                    )
                )

            # Stale or excluded sources
            if freshness_stale_count > 0:
                warnings.append(
                    CriticWarning(
                        code="stale_source",
                        detail=f"{freshness_stale_count} cited source(s) are stale or expired.",
                        severity_level=1,
                    )
                )
            if freshness_all_excluded_fallback:
                warnings.append(
                    CriticWarning(
                        code="stale_source",
                        detail=(
                            "All sources were excluded by freshness policy; "
                            "fallback sources were used."
                        ),
                        severity_level=2,
                    )
                )

            # OCR quality
            if ocr_low_confidence_chunk_count > 0:
                warnings.append(
                    CriticWarning(
                        code="ocr_low_quality",
                        detail=(
                            f"{ocr_low_confidence_chunk_count} chunk(s) have low OCR confidence."
                        ),
                        severity_level=1,
                    )
                )

            # Table extraction quality
            if table_low_confidence_count > 0:
                warnings.append(
                    CriticWarning(
                        code="table_low_confidence",
                        detail=(
                            f"{table_low_confidence_count} table source(s) "
                            "have low extraction confidence."
                        ),
                        severity_level=1,
                    )
                )

            # Document extraction quality
            if extraction_warning_count > 0:
                warnings.append(
                    CriticWarning(
                        code="extraction_quality",
                        detail=(
                            f"{extraction_warning_count} source(s) "
                            "have document extraction quality issues."
                        ),
                        severity_level=1,
                    )
                )

            max_level = max((w.severity_level for w in warnings), default=0)
            severity: CriticSeverity = _INT_SEVERITY.get(min(max_level, 3), "none")
            requires_refiner = max_level >= self._refiner_min_level and self._refiner_min_level > 0
            refiner_instruction = _build_refiner_instruction(warnings) if requires_refiner else ""

            latency_ms = int((perf_counter() - started) * 1000)
            logger.debug(
                "answer_critic severity=%s warnings=%d requires_refiner=%s latency_ms=%d",
                severity,
                len(warnings),
                requires_refiner,
                latency_ms,
            )
            return CriticResult(
                warnings=warnings,
                severity=severity,
                requires_refiner=requires_refiner,
                refiner_instruction=refiner_instruction,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            logger.warning("answer_critic failed, using fallback: %s", exc)
            return self._fallback()


def _build_refiner_instruction(warnings: list[CriticWarning]) -> str:
    """Build a plain-English instruction for the refiner's LLM prompt."""
    codes = {w.code for w in warnings}
    parts: list[str] = []
    if "no_sources_found" in codes:
        parts.append(
            "State clearly that the information was not found in the available sources "
            "and do not assert any claims."
        )
    if "citation_unsupported" in codes:
        parts.append(
            "Remove all claims that are not directly supported by the validated citations."
        )
    if "source_conflict" in codes:
        parts.append(
            "Acknowledge that sources conflict on some points; do not assert a single "
            "definitive answer where sources disagree — instead note the disagreement."
        )
    if "missing_evidence" in codes:
        parts.append(
            "Qualify claims where evidence is present but insufficient to confirm or deny; "
            "use language like 'the available sources suggest' or 'based on limited evidence'."
        )
    if "stale_source" in codes:
        parts.append(
            "Add a note that some cited sources may be outdated and the information "
            "should be verified against current sources."
        )
    return " ".join(parts)
