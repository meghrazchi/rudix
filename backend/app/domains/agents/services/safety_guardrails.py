from __future__ import annotations

import re
from dataclasses import dataclass

_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|earlier)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(all\s+)?(previous|prior|earlier)\s+instructions?\b", re.IGNORECASE),
    re.compile(r"\boverride\s+(security|policy|guardrails?)\b", re.IGNORECASE),
    re.compile(r"\bsystem\s+prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper\s+message\b", re.IGNORECASE),
    re.compile(r"\bcall\s+tool\b", re.IGNORECASE),
    re.compile(r"\bexfiltrat(e|ion)\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class InjectionCheckResult:
    blocked: bool
    reasons: list[str]


class PromptInjectionGuard:
    """Lightweight heuristic guard for unsafe instruction-like content."""

    def evaluate_request(
        self, *, objective: str, question: str | None, document_query: str | None
    ) -> InjectionCheckResult:
        reasons: list[str] = []
        for field_name, value in (
            ("objective", objective),
            ("question", question),
            ("document_query", document_query),
        ):
            if not value:
                continue
            reason = self._match_reason(value)
            if reason is not None:
                reasons.append(f"{field_name}:{reason}")
        return InjectionCheckResult(blocked=bool(reasons), reasons=reasons)

    def is_instruction_like(self, text: str | None) -> bool:
        if not text:
            return False
        return self._match_reason(text) is not None

    def _match_reason(self, text: str) -> str | None:
        normalized = text.strip()
        if not normalized:
            return None
        for pattern in _PROMPT_INJECTION_PATTERNS:
            if pattern.search(normalized):
                return f"matched_pattern:{pattern.pattern}"
        return None
