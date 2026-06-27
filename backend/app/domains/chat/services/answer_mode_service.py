from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Literal

logger = logging.getLogger("chat.answer_mode")

AnswerMode = Literal["grounded", "guidance"]
GuidanceTopic = Literal["onboarding", "ui_help", "empty_state", "source_scope", "how_to_use"]

_EVIDENCE_REQUIRED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(legal|law|lawsuit|regulation|regulatory|compliance|gdpr|hipaa|soc2?|pci|iso[ _]?27001|"
        r"contract|contractual|liability|indemnif|arbitration|jurisdiction|statutory|legislation|"
        r"breach|penalty|sanction|privacy policy|hr policy|leave policy|benefits? policy|"
        r"employment policy|policy document|handbook|agreement|vendor agreement|nda|"
        r"non-disclosure|intellectual property|patent|trademark|copyright|"
        r"according to|what does .* (say|state)|based on the (document|docs|file|handbook|policy|contract)|"
        r"in the (document|docs|file|handbook|policy|contract)|from the (document|docs|file|handbook|policy|contract)|"
        r"uploaded (document|file)|attached (document|file)|source evidence|source text|quote)"
        r"\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(jira|confluence|slack|sharepoint|google drive|gdrive|dropbox|box|onedrive|"
        r"connector(?:-?grounded)?|connector source|connector sources|external source|external item|"
        r"ticket|issue|thread|channel|email)\b",
        re.IGNORECASE,
    ),
)

_GUIDANCE_PATTERNS: tuple[tuple[re.Pattern[str], GuidanceTopic], ...] = (
    (
        re.compile(
            r"\b(onboarding|getting started|first steps|welcome flow|setup wizard|setup guide|"
            r"new user|new users|new hire|day one|get started|walk me through|guide me through|"
            r"how do i use rudix|how can i use rudix|using rudix|help me use rudix)\b",
            re.IGNORECASE,
        ),
        "onboarding",
    ),
    (
        re.compile(
            r"\b(ui|user interface|screen|page|panel|drawer|sidebar|navigation|menu|button|badge|label|"
            r"dashboard|empty state|empty states|no results|trust panel|answer explanation|citation preview|"
            r"cite panel|what does this (screen|page|panel|button|badge) do|"
            r"what do (citations|these citations) mean|how do i inspect citations|"
            r"where do i click|where can i find)\b",
            re.IGNORECASE,
        ),
        "ui_help",
    ),
    (
        re.compile(
            r"\b(empty state suggestions?|when there is nothing to show|no documents yet|"
            r"no answers yet|no sessions yet|no results yet|empty workspace)\b",
            re.IGNORECASE,
        ),
        "empty_state",
    ),
    (
        re.compile(
            r"\b(source scope|scope selection|scope picker|source scope selection|"
            r"how do i choose a source scope|how do i select sources|select a source scope|"
            r"collection picker|document picker)\b",
            re.IGNORECASE,
        ),
        "source_scope",
    ),
    (
        re.compile(
            r"\b(how do i|how can i|how to|what is the best way to|best way to|can you show me|"
            r"how should i|how do i start)\b",
            re.IGNORECASE,
        ),
        "how_to_use",
    ),
)


@dataclass(frozen=True)
class AnswerModeResult:
    mode: AnswerMode
    topic: GuidanceTopic | None
    reason: str
    latency_ms: int = 0


class AnswerModeService:
    """Fast heuristic classifier for safe general guidance vs grounded answers."""

    @staticmethod
    def _normalize(question: str) -> str:
        return " ".join(question.lower().split())

    @classmethod
    def _matches_evidence_required(cls, normalized_question: str) -> bool:
        return any(pattern.search(normalized_question) for pattern in _EVIDENCE_REQUIRED_PATTERNS)

    @classmethod
    def _guidance_topic(cls, normalized_question: str) -> GuidanceTopic:
        for pattern, topic in _GUIDANCE_PATTERNS:
            if pattern.search(normalized_question):
                return topic
        return "how_to_use"

    def classify(self, *, question: str) -> AnswerModeResult:
        """Return guidance mode only for low-risk product-help questions."""
        started = perf_counter()
        try:
            normalized_question = self._normalize(question)
            if self._matches_evidence_required(normalized_question):
                return AnswerModeResult(
                    mode="grounded",
                    topic=None,
                    reason="evidence_required",
                    latency_ms=int((perf_counter() - started) * 1000),
                )

            for pattern, topic in _GUIDANCE_PATTERNS:
                if pattern.search(normalized_question):
                    return AnswerModeResult(
                        mode="guidance",
                        topic=topic,
                        reason=f"safe_guidance:{topic}",
                        latency_ms=int((perf_counter() - started) * 1000),
                    )

            return AnswerModeResult(
                mode="grounded",
                topic=None,
                reason="default_grounded",
                latency_ms=int((perf_counter() - started) * 1000),
            )
        except Exception as exc:
            logger.warning("answer_mode classifier failed, using grounded fallback: %s", exc)
            return AnswerModeResult(
                mode="grounded", topic=None, reason="classifier_error", latency_ms=0
            )
